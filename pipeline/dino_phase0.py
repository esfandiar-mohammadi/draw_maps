#!/usr/bin/env python
"""DINO_IMPROVEMENT_PLAN Phase 0 diagnostic (0.1 + 0.2).

For each in-scope-32 map, at multi-scale, split the graph-F1 gap into a
MASK problem vs a VECTORIZATION problem:

  mask-UB  = skeletonize(raw wall prob > thr) centerline vs GT, same tol band
             -> the best graph-F1 achievable if vectorization were lossless
  graph-F1 = the actual build_graph output (what we ship)

If mask-UB >> graph-F1, the vectorizer is the bottleneck (Phase 1.4/2.4 edge work).
If mask-UB ~= graph-F1 and both R are low, the MASK misses walls (Phase 1.1/1.2
recall losses, Phase 2 resolution). Also flags the worst-recall maps for the
0.2 taxonomy (look at their overlays).

  .venv/bin/python pipeline/dino_phase0.py --ckpt pipeline/models/wall_dino_fa_inscope.pt --per_map
"""
import os, sys, argparse
import numpy as np
from skimage.morphology import skeletonize
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt
from graph_eval_uvtt import raster, dil
import graph_eval_dino as G
import graph_infer
from graph_eval_dino_ms import ms_predict


def prf(pred, gt, tol):
    if pred.sum() == 0:
        return 0.0, 0.0, 0.0
    P = float((pred & dil(gt, tol)).sum()) / float(pred.sum())
    R = float((gt & dil(pred, tol)).sum()) / float(gt.sum())
    F = 2 * P * R / (P + R + 1e-9)
    return P, R, F


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="pipeline/models/wall_dino_fa_inscope.pt")
    ap.add_argument("--scales", default="768,1024,1536")
    ap.add_argument("--wall_thr", type=float, default=0.4)
    ap.add_argument("--fa_list", default="corpus/fa_test_inscope.txt")
    ap.add_argument("--per_map", action="store_true")
    a = ap.parse_args()
    G.CKPT = a.ckpt
    scales = [int(x) for x in a.scales.split(",")]
    slugs = [ln.strip() for ln in open(a.fa_list) if ln.strip()]
    rows = []
    for s in slugs:
        p = os.path.join("corpus/fa", s + ".dd2vtt")
        if not os.path.exists(p):
            continue
        r = load_uvtt(p)
        if r["image"] is None or not r["walls"]:
            continue
        wall, junc, sc = ms_predict(r["image"], scales)
        RH, RW = wall.shape
        gt = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]], (RH, RW))
        tol = max(4, 0.4 * r["ppg"] * sc)
        # mask upper-bound: skeleton centerline of the thresholded prob map
        skel = skeletonize(wall > a.wall_thr)
        mP, mR, mF = prf(skel, gt, tol)
        # actual graph output
        nodes, edges = graph_infer.build_graph(wall, junc, wall_thr=a.wall_thr)
        segs = [(nodes[i][0], nodes[i][1], nodes[j][0], nodes[j][1]) for i, j, t in edges]
        gP, gR, gF = prf(raster(segs, (RH, RW)), gt, tol)
        rows.append((s, mP, mR, mF, gP, gR, gF))
        if a.per_map:
            print(f"{s:34s} mask-UB P={mP:.2f} R={mR:.2f} F={mF:.2f} | "
                  f"graph P={gP:.2f} R={gR:.2f} F={gF:.2f} | vec-loss={mF - gF:+.2f}", flush=True)
    if rows:
        A = np.array([r[1:] for r in rows], np.float32)
        mP, mR, mF, gP, gR, gF = A.mean(0)
        print(f"\nMEAN in-scope n={len(rows)}  [thr={a.wall_thr}, scales={scales}]")
        print(f"  MASK-UB   P={mP:.3f} R={mR:.3f} F1={mF:.3f}")
        print(f"  GRAPH     P={gP:.3f} R={gR:.3f} F1={gF:.3f}")
        print(f"  vec-loss (mask-UB F1 - graph F1) = {mF - gF:+.3f}")
        print(f"  mask recall ceiling = {mR:.3f}  (if this is low, the MASK misses walls)")
        worst = sorted(rows, key=lambda r: r[5])[:6]
        print("  worst-recall maps (0.2 taxonomy — look at overlays):",
              ", ".join(f"{w[0]}({w[5]:.2f})" for w in worst))


if __name__ == "__main__":
    main()
