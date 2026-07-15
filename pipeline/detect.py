#!/usr/bin/env python
"""Headless wall-detection pipeline using Auto-Wall's OpenCV engine.

Loads a battlemap, downscales to a working resolution, runs Auto-Wall's
edge-based (or color-based) wall detection, converts the detected contours to
Foundry VTT wall documents (pixel coords), and writes:
  <out>/walls.json      Foundry wall documents (array, "c":[x0,y0,x1,y1])
  <out>/bg.webp         the downscaled map used as the scene background
  <out>/overlay.png     the map with detected walls drawn in red (for judging)
  <out>/metrics.json    segment count, total length, params, sizes
"""
import os, sys, json, argparse
import cv2, numpy as np

AW = os.path.join(os.path.dirname(__file__), "..", "vendor", "auto-wall")
sys.path.insert(0, os.path.abspath(AW))
from src.wall_detection.detector import detect_walls          # noqa: E402
from src.wall_detection.mask_editor import contours_to_foundry_walls  # noqa: E402


def run(inp, out, work_edge=2500, min_area=100, blur=5, c1=50, c2=150,
        simplify=0.001, max_len=60, merge=4.0, max_walls=6000):
    os.makedirs(out, exist_ok=True)
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"could not read {inp}")
    H0, W0 = img.shape[:2]
    scale = min(1.0, work_edge / max(H0, W0))
    work = cv2.resize(img, (round(W0 * scale), round(H0 * scale)),
                      interpolation=cv2.INTER_AREA) if scale < 1.0 else img.copy()
    Hh, Ww = work.shape[:2]

    contours = detect_walls(work, min_contour_area=min_area, blur_kernel_size=blur,
                            canny_threshold1=c1, canny_threshold2=c2)
    walls = contours_to_foundry_walls(
        contours, work.shape, simplify_tolerance=simplify, max_wall_length=max_len,
        max_walls=max_walls, merge_distance=merge, grid_size=0)

    # overlay
    ov = work.copy()
    tot = 0.0
    for w in walls:
        x0, y0, x1, y1 = w["c"]
        cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        tot += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5

    cv2.imwrite(os.path.join(out, "overlay.png"), ov)
    cv2.imwrite(os.path.join(out, "bg.webp"), work, [cv2.IMWRITE_WEBP_QUALITY, 90])
    json.dump(walls, open(os.path.join(out, "walls.json"), "w"))
    metrics = {"input": os.path.basename(inp), "orig_size": [W0, H0],
               "work_size": [Ww, Hh], "scale": round(scale, 4),
               "n_contours": len(contours), "n_walls": len(walls),
               "total_wall_len_px": round(tot, 1),
               "params": {"min_area": min_area, "blur": blur, "canny": [c1, c2],
                          "simplify": simplify, "max_len": max_len, "merge": merge}}
    json.dump(metrics, open(os.path.join(out, "metrics.json"), "w"), indent=1)
    print(json.dumps(metrics))
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--work-edge", type=int, default=2500)
    ap.add_argument("--min-area", type=int, default=100)
    ap.add_argument("--blur", type=int, default=5)
    ap.add_argument("--c1", type=int, default=50)
    ap.add_argument("--c2", type=int, default=150)
    ap.add_argument("--simplify", type=float, default=0.001)
    ap.add_argument("--max-len", type=int, default=60)
    ap.add_argument("--merge", type=float, default=4.0)
    a = ap.parse_args()
    run(a.input, a.out, a.work_edge, a.min_area, a.blur, a.c1, a.c2,
        a.simplify, a.max_len, a.merge)
