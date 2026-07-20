"""Multi-scale INFERENCE variant of graph_eval_dino: run the DinoSeg predictor at
several long-edge scales (image pyramid), fuse the wall/junction probability maps
at a common reference resolution, then build the planar graph once. Tests whether
multi-scale helps the FA expert WITHOUT any architecture change or retraining.
Same metric protocol as graph_eval_dino (1024 ref long edge, tol band)."""
import os, sys, glob, argparse
import numpy as np, cv2, torch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt
from graph_eval_uvtt import raster, dil
import graph_eval_dino as G
import graph_infer


def ms_predict(img, scales, ref_long=1024):
    """Predict wall/junc at each scale, resize to the ref-resolution work grid, average."""
    H0, W0 = img.shape[:2]
    rsc = min(1.0, ref_long / max(H0, W0))
    RW, RH = round(W0 * rsc), round(H0 * rsc)
    wsum = np.zeros((RH, RW), np.float32); jsum = np.zeros((RH, RW), np.float32)
    for s in scales:
        sc = min(1.0, s / max(H0, W0))
        work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        w, j = G.predict(work)                      # tile=SZ=252 over this scale
        wsum += cv2.resize(w, (RW, RH))
        jsum += cv2.resize(j, (RW, RH))
    return wsum / len(scales), jsum / len(scales), rsc


def evalmap_ms(path, scales, ref_long=1024):
    r = load_uvtt(path)
    if r["image"] is None or not r["walls"]:
        return None
    wall, junc, sc = ms_predict(r["image"], scales, ref_long)
    RH, RW = wall.shape
    nodes, edges = graph_infer.build_graph(wall, junc)
    pred_segs = [(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]) for a, b, t in edges]
    gt = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]], (RH, RW))
    pred = raster(pred_segs, (RH, RW))
    if pred.sum() == 0:
        return (0.0, 0.0, 0.0)
    tol = max(4, 0.4 * r["ppg"] * sc)
    P = float((pred & dil(gt, tol)).sum()) / float(pred.sum())
    R = float((gt & dil(pred, tol)).sum()) / float(gt.sum())
    F = 2 * P * R / (P + R + 1e-9)
    return round(P, 3), round(R, 3), round(F, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="pipeline/models/wall_dino_fa.pt")
    ap.add_argument("--scales", default="768,1024,1536")
    ap.add_argument("--per_map", action="store_true")
    a = ap.parse_args()
    G.CKPT = a.ckpt
    scales = [int(x) for x in a.scales.split(",")]
    slugs = [ln.strip() for ln in open("corpus/fa_test.txt") if ln.strip()]
    maps = [(s, os.path.join("corpus/fa", s + ".dd2vtt")) for s in slugs]
    Ps, Rs, Fs = [], [], []
    for n, p in maps:
        if not p or not os.path.exists(p):
            continue
        res = evalmap_ms(p, scales)
        if res is None:
            continue
        P, R, F = res; Ps.append(P); Rs.append(R); Fs.append(F)
        if a.per_map:
            print(f"{n:36s} MS-DINO  P={P:.2f} R={R:.2f} F1={F:.2f}", flush=True)
    if Ps:
        print(f"\nMEAN MS-DINO scales={scales} [FA held-out (n={len(Ps)})]  "
              f"P={np.mean(Ps):.3f} R={np.mean(Rs):.3f} F1={np.mean(Fs):.3f}")


if __name__ == "__main__":
    main()
