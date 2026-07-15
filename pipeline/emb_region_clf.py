#!/usr/bin/env python
"""Region 'wall vs not-wall' classifier using PRETRAINED embeddings.

Instead of 8 hand-crafted features + RandomForest, embed each SAM region crop
with a frozen pretrained vision backbone (DINOv2, fallback ResNet50) and train a
light head (logistic regression) on the pretrained latent vectors. Same UVTT
ground-truth labels and same train/test split as the hand-feature baseline, so
the two are directly comparable.
"""
import os, sys, glob
import numpy as np, cv2, torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_walls import sam_masks  # noqa: E402
from uvtt import load as load_uvtt                        # noqa: E402
from train_region_clf import gt_wall_mask                 # noqa: E402


def load_backbone():
    dev = "cuda"
    try:
        m = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14", verbose=False)
        m.eval().to(dev)
        mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1)
        def emb(batch):  # batch: [B,3,224,224] float 0..1 (RGB)
            x = (batch.to(dev) - mean) / std
            with torch.no_grad():
                return m(x).cpu().numpy()
        print("backbone: DINOv2 ViT-S/14 (384-d)")
        return emb
    except Exception as e:
        print("DINOv2 failed, using ResNet50:", str(e)[:120])
        from torchvision.models import resnet50, ResNet50_Weights
        import torch.nn as nn
        w = ResNet50_Weights.IMAGENET1K_V2
        m = resnet50(weights=w); m.fc = nn.Identity(); m.eval().to(dev)
        mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1)
        def emb(batch):
            x = (batch.to(dev) - mean) / std
            with torch.no_grad():
                return m(x).cpu().numpy()
        print("backbone: ResNet50 (2048-d)")
        return emb


def region_crop(work, m, pad=0.15, sz=224):
    ys, xs = np.where(m)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bw, bh = x1 - x0, y1 - y0
    px, py = int(bw * pad) + 2, int(bh * pad) + 2
    x0, x1 = max(0, x0 - px), min(work.shape[1], x1 + px)
    y0, y1 = max(0, y0 - py), min(work.shape[0], y1 + py)
    crop = work[y0:y1, x0:x1].copy()
    if crop.size == 0:
        return None
    crop = cv2.resize(crop, (sz, sz), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0


def harvest(paths, emb_fn, work_edge=1536, keep_thr=0.5, prop_thr=0.15, batch=64):
    from region_classifier import region_features, FEATS
    crops, hand, labels = [], [], []
    for p in paths:
        try:
            r = load_uvtt(p)
        except Exception:
            continue
        if r["image"] is None or not r["walls"]:
            continue
        H0, W0 = r["image"].shape[:2]
        sc = min(1.0, work_edge / max(H0, W0))
        work = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY).astype(np.float32)
        d = 255 - gray
        dark = np.clip((d - np.percentile(d, 50)) / (np.percentile(d, 99) - np.percentile(d, 50) + 1e-6), 0, 1)
        thick = max(3, int(r["ppg"] * sc / 3))
        gt = gt_wall_mask(r["walls"], work.shape[:2], sc, thick).astype(bool)
        masks = sam_masks(work)
        for m in masks:
            a = int(m.sum())
            if a < 0.0006 * m.size or a > 0.85 * m.size:
                continue
            bnd = (cv2.dilate(m, np.ones((3, 3), np.uint8), 2) -
                   cv2.erode(m, np.ones((3, 3), np.uint8), 1)).astype(bool)
            if bnd.sum() < 20:
                continue
            ov = float(gt[bnd].mean())
            lab = 1 if ov >= keep_thr else (0 if ov <= prop_thr else None)
            if lab is None:
                continue
            c = region_crop(work, m)
            f = region_features(m, work, hsv, dark)
            if c is None or f is None:
                continue
            crops.append(c); hand.append([f[k] for k in FEATS]); labels.append(lab)
    embs = []
    for i in range(0, len(crops), batch):
        b = np.stack(crops[i:i + batch]).transpose(0, 3, 1, 2)
        embs.append(emb_fn(torch.from_numpy(b)))
    Xe = np.concatenate(embs) if embs else np.zeros((0, 1))
    return Xe, np.array(hand, dtype=np.float32), np.array(labels)


def main():
    emb_fn = load_backbone()
    paths = sorted(glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True))
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(paths)); nt = int(0.8 * len(paths))
    tr = [paths[i] for i in idx[:nt]]; te = [paths[i] for i in idx[nt:]]
    print("harvest+embed train..."); Etr, Htr, ytr = harvest(tr, emb_fn)
    print("harvest+embed test...");  Ete, Hte, yte = harvest(te, emb_fn)
    print(f"train emb{Etr.shape} hand{Htr.shape} keep={int((ytr==1).sum())} prop={int((ytr==0).sum())}")
    print(f"test  emb{Ete.shape} hand{Hte.shape} keep={int((yte==1).sum())} prop={int((yte==0).sum())}")
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import f1_score, precision_score, recall_score
    import joblib

    def report(name, clf, Xtr, Xte):
        clf.fit(Xtr, ytr); pred = clf.predict(Xte)
        pk = precision_score(yte, pred, pos_label=0); rk = recall_score(yte, pred, pos_label=0)
        print(f"{name:32s} PROP P={pk:.3f} R={rk:.3f} | keepP={precision_score(yte,pred,pos_label=1):.3f} "
              f"keepR={recall_score(yte,pred,pos_label=1):.3f} | acc={(pred==yte).mean():.3f}")
        return clf

    lr = lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, class_weight="balanced"))
    rf = lambda: RandomForestClassifier(n_estimators=300, max_depth=10, class_weight="balanced", random_state=0)
    Ctr = np.concatenate([StandardScaler().fit(Etr).transform(Etr), Htr], axis=1)
    Cte = np.concatenate([StandardScaler().fit(Etr).transform(Ete), Hte], axis=1)
    print("=== comparison (held-out) ===")
    report("hand features (RandomForest)", rf(), Htr, Hte)
    report("DINOv2 embedding (LogReg)", lr(), Etr, Ete)
    best = report("embedding + hand (LogReg)", lr(), Ctr, Cte)
    joblib.dump({"clf": best, "kind": "emb+hand"}, "pipeline/models/region_clf_emb.joblib")
    print("saved combined model -> pipeline/models/region_clf_emb.joblib")


if __name__ == "__main__":
    main()
