#!/usr/bin/env python
"""Post-process a wall-segmentation probability map into clean, CONNECTED wall
lines (Foundry walls).

Walls are continuous strokes broken only by doors/windows. So we:
  1. snap to the map's grid,
  2. keep a grid edge if the seg probability covers it,
  3. merge collinear edges into long runs and bridge tiny (sub-door) gaps from
     detection noise, while leaving door-sized (>=1 cell) gaps OPEN,
  4. weld dangling ends onto crossing walls (junctions share vertices -> no
     light leaks),
  5. prune isolated stubs (a wall that connects to nothing is noise).
Reuses the grid machinery already built in grid_walls.
"""
import os, sys, json, argparse
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_detect import run as detect_grid
from grid_walls import merge_runs, weld_endpoints, prune_isolated, foundry_wall
import infer_seg


def run(inp, out, work_edge=1536, cov_min=0.35, prob_thr=0.4, gap_close=0,
        weld=1, prune=2, min_conf=3.0):
    os.makedirs(out, exist_ok=True)
    g = detect_grid(inp)
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    H0, W0 = img.shape[:2]
    sc = min(1.0, work_edge / max(H0, W0))
    work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA) if sc < 1 else img
    Hh, Ww = work.shape[:2]
    prob = infer_seg.predict(work)                    # wall probability at work res
    wm = np.clip(prob / max(prob.max(), 1e-6), 0, 1).astype(np.float32)

    if g["conf"] < min_conf:
        # no reliable grid: threshold+skeletonise prob into raw polylines
        binm = (prob > prob_thr).astype(np.uint8) * 255
        cv2.imwrite(os.path.join(out, "wallness.png"), (wm * 255).astype(np.uint8))
        json.dump({"input": os.path.basename(inp), "used_grid": False},
                  open(os.path.join(out, "metrics.json"), "w"))
        print(json.dumps({"input": os.path.basename(inp), "used_grid": False}))
        return

    gs = g["grid"] * sc
    ox = (g["offset_x"] * sc) % gs; oy = (g["offset_y"] * sc) % gs
    xs = np.arange(ox, Ww - 1, gs); ys = np.arange(oy, Hh - 1, gs)
    nx, ny = len(xs), len(ys)

    def cov(p0, p1, horiz):
        if horiz:
            y = int(round(p0[1])); x0, x1 = int(round(p0[0])), int(round(p1[0]))
            strip = wm[max(0, y - 2):y + 3, x0:x1]; prof = strip.max(0) if strip.size else np.array([0.])
        else:
            x = int(round(p0[0])); y0, y1 = int(round(p0[1])), int(round(p1[1]))
            strip = wm[y0:y1, max(0, x - 2):x + 3]; prof = strip.max(1) if strip.size else np.array([0.])
        return float((prof > prob_thr).mean()) if prof.size else 0.0
    Hflag = np.zeros((ny, nx - 1), bool); Vflag = np.zeros((nx, ny - 1), bool)
    for j in range(ny):
        for i in range(nx - 1):
            Hflag[j, i] = cov((xs[i], ys[j]), (xs[i + 1], ys[j]), True) >= cov_min
    for i in range(nx):
        for j in range(ny - 1):
            Vflag[i, j] = cov((xs[i], ys[j]), (xs[i], ys[j + 1]), False) >= cov_min

    raw = []
    for (j, i0, i1) in merge_runs(Hflag, gap_close):
        y = oy + j * gs; raw.append((ox + i0 * gs, y, ox + (i1 + 1) * gs, y))
    for (i, j0, j1) in merge_runs(Vflag, gap_close):
        x = ox + i * gs; raw.append((x, oy + j0 * gs, x, oy + (j1 + 1) * gs))
    if weld > 0:
        raw = weld_endpoints(raw, ox, oy, gs, nx, ny, weld)
    if prune > 0:
        raw = prune_isolated(raw, gs, max_len_cells=prune)

    walls, seen, tot = [], set(), 0.0
    ov = work.copy()
    for (x0, y0, x1, y1) in raw:
        key = (round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1))
        if (x0 == x1 and y0 == y1) or key in seen:
            continue
        seen.add(key); walls.append(foundry_wall(x0, y0, x1, y1))
        cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        tot += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    cv2.imwrite(os.path.join(out, "overlay.png"), ov)
    cv2.imwrite(os.path.join(out, "wallness.png"), (wm * 255).astype(np.uint8))
    cv2.imwrite(os.path.join(out, "bg.webp"), work, [cv2.IMWRITE_WEBP_QUALITY, 90])
    json.dump(walls, open(os.path.join(out, "walls.json"), "w"))
    m = {"input": os.path.basename(inp), "used_grid": True, "n_walls": len(walls),
         "work_size": [Ww, Hh], "total_wall_len_px": round(tot, 1)}
    json.dump(m, open(os.path.join(out, "metrics.json"), "w"), indent=1)
    print(json.dumps(m))
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    run(a.input, a.out)
