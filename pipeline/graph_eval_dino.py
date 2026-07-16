"""Precision/Recall/F1 of the planar graph built from the fine-tuned DINOv2
ViT-g (DinoSeg, wall+junction) vs UVTT ground truth on the held-out hard maps.
Same protocol as graph_eval_uvtt (1024 long edge, centreline + tolerance band);
only the predictor differs (tile 252 = DINOv2 patch multiple, vs U-Net 256).
"""
import os, sys, glob, argparse
import numpy as np, cv2, torch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt
from train_dino import DinoSeg, SZ
from train_seg import IMEAN, ISTD
from graph_eval_uvtt import raster, dil
import graph_infer

DEV = "cuda"
_m = None
CKPT = "pipeline/models/wall_dino_vitg.pt"


def model():
    global _m
    if _m is None:
        m = DinoSeg().to(DEV)
        m.load_state_dict(torch.load(CKPT, map_location=DEV))
        m.eval(); _m = m
    return _m


def predict(work, tile=SZ):
    H, W = work.shape[:2]
    wall = np.zeros((H, W), np.float32); junc = np.zeros((H, W), np.float32); cnt = np.zeros((H, W), np.float32)
    xs = sorted(set(list(range(0, max(1, W - tile) + 1, tile)) + [max(0, W - tile)]))
    ys = sorted(set(list(range(0, max(1, H - tile) + 1, tile)) + [max(0, H - tile)]))
    for y in ys:
        for x in xs:
            crop = work[y:y + tile, x:x + tile]; ch, cw = crop.shape[:2]
            c = cv2.resize(crop, (tile, tile))
            xx = (cv2.cvtColor(c, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
            with torch.no_grad():
                out = torch.sigmoid(model()(torch.from_numpy(xx.transpose(2, 0, 1))[None].to(DEV)))[0].cpu().numpy()
            wall[y:y + ch, x:x + cw] += cv2.resize(out[0], (tile, tile))[:ch, :cw]
            junc[y:y + ch, x:x + cw] += cv2.resize(out[1], (tile, tile))[:ch, :cw]
            cnt[y:y + ch, x:x + cw] += 1
    return wall / np.maximum(cnt, 1), junc / np.maximum(cnt, 1)


def evalmap(path, long_edge=1024, overlay=None):
    r = load_uvtt(path)
    if r["image"] is None or not r["walls"]:
        return None
    H0, W0 = r["image"].shape[:2]
    sc = min(1.0, long_edge / max(H0, W0))
    work = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
    wall, junc = predict(work)
    nodes, edges = graph_infer.build_graph(wall, junc)
    pred_segs = [(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]) for a, b, t in edges]
    gt = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]], work.shape[:2])
    pred = raster(pred_segs, work.shape[:2])
    if overlay:
        ov = (work * 0.55).astype(np.uint8)
        for a, b, t in edges:
            cv2.line(ov, tuple(map(int, nodes[a])), tuple(map(int, nodes[b])), (0, 0, 255), 2)
        for (x, y) in nodes:
            cv2.circle(ov, (int(x), int(y)), 2, (0, 255, 255), -1)
        cv2.imwrite(overlay, ov)
    if pred.sum() == 0:
        return (0.0, 0.0, 0.0)
    tol = max(4, 0.4 * r["ppg"] * sc)
    P = float((pred & dil(gt, tol)).sum()) / float(pred.sum())
    R = float((gt & dil(pred, tol)).sum()) / float(gt.sum())
    F = 2 * P * R / (P + R + 1e-9)
    return round(P, 3), round(R, 3), round(F, 3)


def main():
    global CKPT
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlays", default="corpus/results")
    ap.add_argument("--ckpt", default=CKPT)
    ap.add_argument("--tag", default="DINO_graph")
    a = ap.parse_args()
    CKPT = a.ckpt
    want = ["void-town", "goblin-travel-train", "desert-tavern", "road-side-in",
            "festival-of-fools", "little-fish-academy"]
    allp = glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True)
    Ps, Rs, Fs = [], [], []
    for n in want:
        p = next((x for x in allp if os.path.basename(x) == n + ".dd2vtt"), None)
        if not p:
            continue
        r = evalmap(p, overlay=os.path.join(a.overlays, f"{a.tag}_{n}.png"))
        if r is None:
            continue
        P, R, F = r; Ps.append(P); Rs.append(R); Fs.append(F)
        print(f"{n:32s} DINO-GRAPH  P={P:.2f} R={R:.2f} F1={F:.2f}", flush=True)
    if Ps:
        print(f"\nMEAN DINO-GRAPH  P={np.mean(Ps):.3f} R={np.mean(Rs):.3f} F1={np.mean(Fs):.3f}")


if __name__ == "__main__":
    main()
