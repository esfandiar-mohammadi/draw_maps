#!/usr/bin/env python
"""Train the region 'wall vs not-wall' classifier on REAL labels from UVTT
ground truth (mbround18/vtt-maps .dd2vtt files).

For each map: run SAM -> regions; rasterise the ground-truth walls; label each
region KEEP(1) if its boundary lies on ground-truth walls, PROP(0) if it does
not. Train a RandomForest on shape/colour features. This replaces the degenerate
weak-labelling with genuine supervision.
"""
import os, sys, glob, json
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_walls import sam_masks           # noqa: E402
from region_classifier import region_features, FEATS  # noqa: E402
from uvtt import load as load_uvtt        # noqa: E402


def gt_wall_mask(walls, shape, sc, thick):
    m = np.zeros(shape, np.uint8)
    for x0, y0, x1, y1 in walls:
        cv2.line(m, (int(x0 * sc), int(y0 * sc)), (int(x1 * sc), int(y1 * sc)), 255, thick)
    return m


def build(paths, work_edge=1536, keep_thr=0.5, prop_thr=0.15):
    X, y = [], []
    for p in paths:
        try:
            r = load_uvtt(p)
        except Exception as e:
            print("  skip", os.path.basename(p), e); continue
        img = r["image"]
        if img is None or not r["walls"]:
            continue
        H0, W0 = img.shape[:2]
        sc = min(1.0, work_edge / max(H0, W0))
        work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        Hh, Ww = work.shape[:2]
        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY).astype(np.float32)
        d = 255 - gray
        dark = np.clip((d - np.percentile(d, 50)) / (np.percentile(d, 99) - np.percentile(d, 50) + 1e-6), 0, 1)
        thick = max(3, int(r["ppg"] * sc / 3))
        gt = gt_wall_mask(r["walls"], (Hh, Ww), sc, thick).astype(bool)
        masks = sam_masks(work)
        n = 0
        for m in masks:
            f = region_features(m, work, hsv, dark)
            if f is None or f["area_frac"] > 0.85:
                continue
            bnd = (cv2.dilate(m, np.ones((3, 3), np.uint8), 2) -
                   cv2.erode(m, np.ones((3, 3), np.uint8), 1)).astype(bool)
            if bnd.sum() < 20:
                continue
            overlap = float(gt[bnd].mean())
            if overlap >= keep_thr:
                lab = 1
            elif overlap <= prop_thr:
                lab = 0
            else:
                continue
            X.append([f[k] for k in FEATS]); y.append(lab); n += 1
        print(f"  {os.path.basename(p):45s} walls={len(r['walls']):3d} masks={len(masks):3d} labelled={n}")
    return np.array(X), np.array(y)


def main():
    paths = sorted(glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True))
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(paths))
    n_train = int(0.8 * len(paths))
    train_p = [paths[i] for i in idx[:n_train]]
    test_p = [paths[i] for i in idx[n_train:]]
    print(f"{len(paths)} maps -> {len(train_p)} train, {len(test_p)} test")
    print("== building train ==")
    Xtr, ytr = build(train_p)
    print("== building test ==")
    Xte, yte = build(test_p)
    print(f"train regions {len(ytr)} (keep={int((ytr==1).sum())}, prop={int((ytr==0).sum())})")
    print(f"test  regions {len(yte)} (keep={int((yte==1).sum())}, prop={int((yte==0).sum())})")
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import classification_report
    clf = RandomForestClassifier(n_estimators=300, max_depth=10,
                                 class_weight="balanced", random_state=0)
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    print(classification_report(yte, pred, target_names=["prop", "keep"], digits=3))
    print("feature importance:", dict(zip(FEATS, np.round(clf.feature_importances_, 3))))
    import joblib
    os.makedirs("pipeline/models", exist_ok=True)
    joblib.dump({"clf": clf, "feats": FEATS}, "pipeline/models/region_clf.joblib")
    print("saved pipeline/models/region_clf.joblib")


if __name__ == "__main__":
    main()
