#!/usr/bin/env python
"""Auto-select wall-detection mode.

If a confident square grid is found, use the grid-aware special case
(pipeline/grid_walls) — walls snapped to grid edges, no diagonals, few long
segments. Otherwise fall back to the generic contour/edge detector
(pipeline/detect). Same output layout either way.
"""
import os, sys, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_detect import run as detect_grid   # noqa: E402
import grid_walls, detect                     # noqa: E402


def run(inp, out, min_conf=3.0, k=1.2):
    g = detect_grid(inp)
    if g["conf"] >= min_conf:
        print(f"[auto] grid conf {g['conf']} >= {min_conf}: GRID mode (grid={g['grid']}px)")
        return grid_walls.run(inp, out, k=k, min_conf=min_conf)
    print(f"[auto] grid conf {g['conf']} < {min_conf}: generic edge/contour mode")
    return detect.run(inp, out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--min-conf", type=float, default=3.0)
    ap.add_argument("--k", type=float, default=1.2)
    a = ap.parse_args()
    run(a.input, a.out, a.min_conf, a.k)
