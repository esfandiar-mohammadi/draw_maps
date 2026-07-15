"""Precision/Recall/F1 of the PLANAR-GRAPH edges vs UVTT ground-truth walls,
on the held-out hard maps (centreline comparison, tolerance band)."""
import os, sys, glob
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt
import graph_infer


def raster(segs, shape, thick=1):
    m = np.zeros(shape, np.uint8)
    for x0, y0, x1, y1 in segs:
        cv2.line(m, (int(x0), int(y0)), (int(x1), int(y1)), 255, thick)
    return m > 0


def dil(mask, tol):
    k = 2 * int(tol) + 1
    return cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0


def evalmap(path, long_edge=1024):
    r = load_uvtt(path)
    if r["image"] is None or not r["walls"]:
        return None
    H0, W0 = r["image"].shape[:2]
    sc = min(1.0, long_edge / max(H0, W0))
    work = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
    wall, junc = graph_infer.predict(work)
    nodes, edges = graph_infer.build_graph(wall, junc)
    pred_segs = [(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]) for a, b, t in edges]
    gt = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]], work.shape[:2])
    pred = raster(pred_segs, work.shape[:2])
    if pred.sum() == 0:
        return (0.0, 0.0, 0.0)
    tol = max(4, 0.4 * r["ppg"] * sc)
    P = float((pred & dil(gt, tol)).sum()) / float(pred.sum())
    R = float((gt & dil(pred, tol)).sum()) / float(gt.sum())
    F = 2 * P * R / (P + R + 1e-9)
    return round(P, 3), round(R, 3), round(F, 3)


def main():
    want = ["void-town", "goblin-travel-train", "desert-tavern", "road-side-in",
            "festival-of-fools", "little-fish-academy"]
    allp = glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True)
    Ps, Rs, Fs = [], [], []
    for n in want:
        p = next((x for x in allp if os.path.basename(x) == n + ".dd2vtt"), None)
        if not p:
            continue
        r = evalmap(p)
        if r is None:
            continue
        P, R, F = r; Ps.append(P); Rs.append(R); Fs.append(F)
        print(f"{n:32s} GRAPH  P={P:.2f} R={R:.2f} F1={F:.2f}")
    if Ps:
        print(f"\nMEAN GRAPH  P={np.mean(Ps):.3f} R={np.mean(Rs):.3f} F1={np.mean(Fs):.3f}")


if __name__ == "__main__":
    main()
