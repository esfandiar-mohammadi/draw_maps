#!/usr/bin/env python
"""Grid-aware wall detection (special case for gridded battlemaps), v2.

Premise (verified): battlemaps carry a square grid of a round pixel size and
walls run ALONG grid edges. We detect the grid, then decide per grid edge
whether a wall lies on it, snap walls to the grid, and clean up.

v2 improvements over v1:
- CONTRAST scoring instead of absolute darkness: a wall is a dark *ridge* —
  darker than the lighter of its two neighbouring cell interiors. This rejects
  false positives inside large dark areas (carpets, dark tiled floors) where an
  edge is NOT darker than its neighbours.
- CONTINUITY (coverage) gate: the dark ridge must span most of the edge, so
  patchy decor/props don't register.
- GAP CLOSING: small breaks along a collinear run are bridged so outlines form
  connected walls (light/vision leaks otherwise).
- PARALLEL DEDUP: two parallel walls one cell apart with wall material between
  them are two sides of ONE wall -> keep a single line (connectivity kept on
  the integer grid). A corridor (floor between) is left as two walls.
- WELD/DEDUP: drop zero-length and duplicate segments; endpoints already sit on
  shared grid nodes so perpendicular walls join cleanly.

Output matches pipeline/detect.py: walls.json, bg.webp, overlay.png, metrics.json
"""
import os, sys, json, argparse
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_detect import run as detect_grid  # noqa: E402


def wallness_map(work):
    """Robustly-normalised darkness, with green foliage down-weighted (walls
    are dark neutral/brown lines, not saturated green)."""
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY).astype(np.float32)
    dark = 255.0 - gray
    lo, hi = np.percentile(dark, 50), np.percentile(dark, 99)
    dark = np.clip((dark - lo) / (hi - lo + 1e-6), 0, 1)
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    h, s = hsv[:, :, 0].astype(np.float32), hsv[:, :, 2].astype(np.float32) / 255.0
    green = ((h >= 35) & (h <= 90)).astype(np.float32) * s  # saturated green
    return np.clip(dark * (1.0 - 0.6 * green), 0, 1)


def cell_darkness(wm, xs, ys, shrink=0.25):
    """Mean wall-ness of each cell interior (shrunk to avoid the grid lines)."""
    nx, ny = len(xs), len(ys)
    CD = np.zeros((ny - 1, nx - 1), np.float32)
    for j in range(ny - 1):
        y0, y1 = ys[j], ys[j + 1]
        dy = (y1 - y0) * shrink
        for i in range(nx - 1):
            x0, x1 = xs[i], xs[i + 1]
            dx = (x1 - x0) * shrink
            patch = wm[int(y0 + dy):int(y1 - dy) + 1, int(x0 + dx):int(x1 - dx) + 1]
            CD[j, i] = patch.mean() if patch.size else 0.0
    return CD


def edge_line_stats(wm, p0, p1, band, horizontal):
    """Along the grid edge from p0 to p1, return (ridge_darkness, coverage).
    ridge_darkness = mean over the edge of the darkest pixel within +/-band.
    coverage = fraction of positions whose darkest band pixel exceeds 0.45."""
    if horizontal:
        y = int(round(p0[1])); x0, x1 = int(round(p0[0])), int(round(p1[0]))
        yb0, yb1 = max(0, y - band), min(wm.shape[0], y + band + 1)
        strip = wm[yb0:yb1, x0:x1]
        prof = strip.max(axis=0) if strip.size else np.array([0.0])
    else:
        x = int(round(p0[0])); y0, y1 = int(round(p0[1])), int(round(p1[1]))
        xb0, xb1 = max(0, x - band), min(wm.shape[1], x + band + 1)
        strip = wm[y0:y1, xb0:xb1]
        prof = strip.max(axis=1) if strip.size else np.array([0.0])
    if prof.size == 0:
        return 0.0, 0.0
    return float(prof.mean()), float((prof > 0.45).mean())


def merge_runs(flags, gap=1):
    """Runs of consecutive True along axis 1, bridging gaps of <= `gap`
    provided both ends of the gap are walls (connectivity)."""
    runs = []
    A, B = flags.shape
    for a in range(A):
        b = 0
        while b < B:
            if flags[a, b]:
                b0 = b; last = b
                while b < B:
                    if flags[a, b]:
                        last = b; b += 1
                    elif b - last <= gap and (b + 1 < B and flags[a, min(b + 1, B - 1)]):
                        b += 1  # bridge a small gap
                    else:
                        break
                runs.append((a, b0, last))
            else:
                b += 1
    return runs


def weld_endpoints(segs, ox, oy, gs, nx, ny, weld=1):
    """Close small corner gaps: extend a dangling wall endpoint by up to `weld`
    grid cells along its own axis if that reaches a node occupied by ANOTHER
    wall (a crossing perpendicular wall or a collinear one). Keeps everything on
    the integer grid so junctions share exact vertices (needed for lighting)."""
    def to_ij(x, y):
        return int(round((x - ox) / gs)), int(round((y - oy) / gs))

    # node -> set of wall indices passing through it (endpoints + interior nodes)
    occ = {}
    norm = []
    for k, (x0, y0, x1, y1) in enumerate(segs):
        i0, j0 = to_ij(x0, y0); i1, j1 = to_ij(x1, y1)
        norm.append([i0, j0, i1, j1])
        if j0 == j1:  # horizontal
            for i in range(min(i0, i1), max(i0, i1) + 1):
                occ.setdefault((i, j0), set()).add(k)
        else:         # vertical
            for j in range(min(j0, j1), max(j0, j1) + 1):
                occ.setdefault((i0, j), set()).add(k)

    def occupied_by_other(node, k):
        s = occ.get(node)
        return bool(s and (s - {k}))

    for k, (i0, j0, i1, j1) in enumerate(norm):
        horiz = (j0 == j1)
        # order endpoints
        if horiz:
            lo, hi = (i0, i1) if i0 <= i1 else (i1, i0)
            # extend low end leftwards, high end rightwards
            for step in range(1, weld + 1):
                if occupied_by_other((lo - step, j0), k):
                    lo -= step; break
            for step in range(1, weld + 1):
                if occupied_by_other((hi + step, j0), k):
                    hi += step; break
            norm[k] = [lo, j0, hi, j0]
        else:
            lo, hi = (j0, j1) if j0 <= j1 else (j1, j0)
            for step in range(1, weld + 1):
                if occupied_by_other((i0, lo - step), k):
                    lo -= step; break
            for step in range(1, weld + 1):
                if occupied_by_other((i0, hi + step), k):
                    hi += step; break
            norm[k] = [i0, lo, i0, hi]

    out = []
    for i0, j0, i1, j1 in norm:
        out.append((ox + i0 * gs, oy + j0 * gs, ox + i1 * gs, oy + j1 * gs))
    return out


def prune_isolated(segs, gs, max_len_cells=2, passes=3):
    """Remove short walls that connect to nothing (both endpoints dangling and
    not lying on another wall). Such stubs are almost always false positives
    (props, decor) — connectivity is itself a false-positive filter. Iterated,
    since removing one stub can isolate its neighbour."""
    segs = list(segs)
    for _ in range(passes):
        from collections import defaultdict
        deg = defaultdict(int)
        for x0, y0, x1, y1 in segs:
            deg[(round(x0, 1), round(y0, 1))] += 1
            deg[(round(x1, 1), round(y1, 1))] += 1

        def on_other(px, py, self_idx):
            for k, (x0, y0, x1, y1) in enumerate(segs):
                if k == self_idx:
                    continue
                if x0 == x1 == px and min(y0, y1) <= py <= max(y0, y1):
                    return True
                if y0 == y1 == py and min(x0, x1) <= px <= max(x0, x1):
                    return True
            return False

        keep = []
        for idx, (x0, y0, x1, y1) in enumerate(segs):
            length = (abs(x1 - x0) + abs(y1 - y0)) / gs
            a_conn = deg[(round(x0, 1), round(y0, 1))] >= 2 or on_other(x0, y0, idx)
            b_conn = deg[(round(x1, 1), round(y1, 1))] >= 2 or on_other(x1, y1, idx)
            if length <= max_len_cells and not a_conn and not b_conn:
                continue  # isolated stub -> drop
            keep.append((x0, y0, x1, y1))
        if len(keep) == len(segs):
            break
        segs = keep
    return segs


def foundry_wall(x0, y0, x1, y1):
    return {"light": 20, "sight": 20, "sound": 20, "move": 20,
            "c": [float(x0), float(y0), float(x1), float(y1)],
            "dir": 0, "door": 0, "ds": 0, "flags": {}}


def run(inp, out, work_edge=3000, band=3, k=1.0, cov_min=0.6,
        gap_close=1, min_conf=3.0, dedup=True, min_contrast=0.12, weld=1, prune=2):
    os.makedirs(out, exist_ok=True)
    g = detect_grid(inp)
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    H0, W0 = img.shape[:2]
    scale = min(1.0, work_edge / max(H0, W0))
    work = cv2.resize(img, (round(W0 * scale), round(H0 * scale)),
                      interpolation=cv2.INTER_AREA) if scale < 1 else img.copy()
    Hh, Ww = work.shape[:2]
    if g["conf"] < min_conf:
        json.dump({"input": os.path.basename(inp), "used_grid": False, "grid_conf": g["conf"]},
                  open(os.path.join(out, "metrics.json"), "w"), indent=1)
        print(json.dumps({"input": os.path.basename(inp), "used_grid": False, "conf": g["conf"]}))
        return

    gs = g["grid"] * scale
    ox = (g["offset_x"] * scale) % gs
    oy = (g["offset_y"] * scale) % gs
    wm = wallness_map(work)
    xs = np.arange(ox, Ww - 1, gs)
    ys = np.arange(oy, Hh - 1, gs)
    nx, ny = len(xs), len(ys)
    CD = cell_darkness(wm, xs, ys)

    def cd(j, i):  # cell darkness with border -> light (0)
        if 0 <= j < ny - 1 and 0 <= i < nx - 1:
            return CD[j, i]
        return 0.0

    # Contrast score per edge = ridge darkness - lighter neighbouring interior.
    Hc = np.zeros((ny, nx - 1)); Hcov = np.zeros((ny, nx - 1))
    for j in range(ny):
        for i in range(nx - 1):
            rid, cov = edge_line_stats(wm, (xs[i], ys[j]), (xs[i + 1], ys[j]), band, True)
            nb = min(cd(j - 1, i), cd(j, i))
            Hc[j, i] = rid - nb; Hcov[j, i] = cov
    Vc = np.zeros((nx, ny - 1)); Vcov = np.zeros((nx, ny - 1))
    for i in range(nx):
        for j in range(ny - 1):
            rid, cov = edge_line_stats(wm, (xs[i], ys[j]), (xs[i], ys[j + 1]), band, False)
            nb = min(cd(j, i - 1), cd(j, i))
            Vc[i, j] = rid - nb; Vcov[i, j] = cov

    allc = np.concatenate([Hc.ravel(), Vc.ravel()])
    med = float(np.median(allc)); mad = float(np.median(np.abs(allc - med))) + 1e-6
    thr = max(min_contrast, med + k * 1.4826 * mad)
    Hflag = (Hc >= thr) & (Hcov >= cov_min)
    Vflag = (Vc >= thr) & (Vcov >= cov_min)

    # Parallel dedup: horizontal walls at rows j and j+1 over the same column i
    # with a WALL cell between them (CD high) are two sides of one wall -> keep
    # the upper one only. Same for vertical (keep the left one).
    dedup_removed = 0
    if dedup:
        wallcell = CD >= max(min_contrast, np.median(CD) + 1.0 * 1.4826 *
                             (np.median(np.abs(CD - np.median(CD))) + 1e-6))
        for i in range(nx - 1):
            for j in range(ny - 1):
                if Hflag[j, i] and Hflag[j + 1, i] and wallcell[j, i]:
                    Hflag[j + 1, i] = False; dedup_removed += 1
        for j in range(ny - 1):
            for i in range(nx - 1):
                if Vflag[i, j] and Vflag[i + 1, j] and wallcell[j, i]:
                    Vflag[i + 1, j] = False; dedup_removed += 1

    raw = []
    for (j, i0, i1) in merge_runs(Hflag, gap_close):
        y = oy + j * gs
        raw.append((ox + i0 * gs, y, ox + (i1 + 1) * gs, y))
    for (i, j0, j1) in merge_runs(Vflag, gap_close):
        x = ox + i * gs
        raw.append((x, oy + j0 * gs, x, oy + (j1 + 1) * gs))

    if weld > 0:
        raw = weld_endpoints(raw, ox, oy, gs, nx, ny, weld)
    if prune > 0:
        raw = prune_isolated(raw, gs, max_len_cells=prune)

    walls, seen = [], set()
    for (x0, y0, x1, y1) in raw:
        key = (round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1))
        if (x0 == x1 and y0 == y1) or key in seen:
            continue
        seen.add(key); walls.append(foundry_wall(x0, y0, x1, y1))

    ov = work.copy(); tot = 0.0
    for w in walls:
        x0, y0, x1, y1 = w["c"]
        cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        tot += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    cv2.imwrite(os.path.join(out, "overlay.png"), ov)
    cv2.imwrite(os.path.join(out, "bg.webp"), work, [cv2.IMWRITE_WEBP_QUALITY, 90])
    json.dump(walls, open(os.path.join(out, "walls.json"), "w"))
    metrics = {"input": os.path.basename(inp), "used_grid": True, "grid_conf": g["conf"],
               "grid_orig_px": g["grid"], "grid_work_px": round(gs, 1),
               "work_size": [Ww, Hh], "n_walls": len(walls),
               "total_wall_len_px": round(tot, 1), "threshold": round(thr, 3),
               "dedup_removed": dedup_removed}
    json.dump(metrics, open(os.path.join(out, "metrics.json"), "w"), indent=1)
    print(json.dumps(metrics))
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--work-edge", type=int, default=3000)
    ap.add_argument("--band", type=int, default=3)
    ap.add_argument("--k", type=float, default=1.0)
    ap.add_argument("--cov-min", type=float, default=0.6)
    ap.add_argument("--gap-close", type=int, default=1)
    ap.add_argument("--no-dedup", action="store_true")
    a = ap.parse_args()
    run(a.input, a.out, a.work_edge, a.band, a.k, a.cov_min, a.gap_close,
        dedup=not a.no_dedup)
