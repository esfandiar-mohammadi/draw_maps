#!/usr/bin/env python
"""Vectorise a wall probability mask into PIECEWISE-LINEAR, CONNECTED polyline
groups (not restricted to the grid).

Walls = a set of polylines. Each polyline is piecewise linear (Douglas-Peucker),
and polylines meet at shared junction vertices so they form connected groups
(components) — a city map yields many small groups (one per building/cluster).
Vertices are shared, so Foundry vision/light does not leak at junctions.

Pipeline: threshold -> skeletonise -> build skeleton graph (junctions/endpoints)
-> trace each edge into a polyline -> simplify -> drop tiny stray components.
"""
import os, sys, json, argparse
import numpy as np, cv2
from skimage.morphology import skeletonize

N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def neighbors(skel, y, x):
    H, W = skel.shape
    out = []
    for dy, dx in N8:
        yy, xx = y + dy, x + dx
        if 0 <= yy < H and 0 <= xx < W and skel[yy, xx]:
            out.append((yy, xx))
    return out


def trace_polylines(skel):
    """Return list of polylines (each a list of (x,y)) from a skeleton."""
    skel = skel.astype(bool)
    deg = np.zeros(skel.shape, np.uint8)
    ys, xs = np.where(skel)
    for y, x in zip(ys, xs):
        deg[y, x] = len(neighbors(skel, y, x))
    is_node = skel & (deg != 2)          # endpoints (1) + junctions (>=3)
    polylines = []
    visited_edge = set()

    def walk(y, x, ny, nx):
        path = [(y, x), (ny, nx)]
        py, px = y, x; cy, cx = ny, nx
        while deg[cy, cx] == 2:
            nxts = [n for n in neighbors(skel, cy, cx) if n != (py, px)]
            if not nxts:
                break
            py, px = cy, cx; cy, cx = nxts[0]
            path.append((cy, cx))
            if (cy, cx) == (y, x):
                break
        return path

    ny_, nx_ = np.where(is_node)
    for y, x in zip(ny_, nx_):
        for (yy, xx) in neighbors(skel, y, x):
            key = frozenset([(y, x), (yy, xx)])
            if key in visited_edge:
                continue
            path = walk(y, x, yy, xx)
            for a, b in zip(path, path[1:]):
                visited_edge.add(frozenset([a, b]))
            polylines.append([(px, py) for py, px in path])
    # isolated loops (all degree 2, no node touched)
    seen = set(e for e in visited_edge)
    for y, x in zip(ys, xs):
        for (yy, xx) in neighbors(skel, y, x):
            key = frozenset([(y, x), (yy, xx)])
            if key not in seen:
                path = walk(y, x, yy, xx)
                for a, b in zip(path, path[1:]):
                    seen.add(frozenset([a, b]))
                polylines.append([(px, py) for py, px in path])
    return polylines


def simplify(poly, eps=2.5):
    if len(poly) < 3:
        return poly
    arr = np.array(poly, np.int32).reshape(-1, 1, 2)
    out = cv2.approxPolyDP(arr, eps, closed=(poly[0] == poly[-1]))
    return [tuple(p[0]) for p in out]


def vectorize(prob, thr=0.4, min_len=8, eps=2.5):
    """The model predicts the filled wall FOOTPRINT (learned, varying thickness),
    so a thick wall is ONE region and its two sides already merge — the skeleton
    is a single centreline. We only close tiny holes for noise, then skeletonise.
    Local wall thickness is read off the distance transform (2x distance at the
    centreline) and attached to each polyline."""
    binm = (prob > thr).astype(np.uint8)
    binm = cv2.morphologyEx(binm, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    dist = cv2.distanceTransform(binm, cv2.DIST_L2, 3)   # px to nearest non-wall
    skel = skeletonize(binm.astype(bool))
    polys = trace_polylines(skel)
    out = []
    for p in polys:
        sp = simplify(p, eps)
        length = sum(((sp[i][0] - sp[i + 1][0]) ** 2 + (sp[i][1] - sp[i + 1][1]) ** 2) ** 0.5
                     for i in range(len(sp) - 1))
        if length >= min_len and len(sp) >= 2:
            th = float(np.median([2 * dist[y, x] for (x, y) in p
                                  if 0 <= y < dist.shape[0] and 0 <= x < dist.shape[1]]) or 0)
            out.append({"pts": sp, "thickness": round(th, 1)})
    return out


def polylines_to_walls(polys):
    walls = []
    for grp in polys:
        pts, th = grp["pts"], grp.get("thickness", 0)
        for a, b in zip(pts, pts[1:]):
            walls.append({"light": 20, "sight": 20, "sound": 20, "move": 20,
                          "c": [float(a[0]), float(a[1]), float(b[0]), float(b[1])],
                          "dir": 0, "door": 0, "ds": 0, "flags": {"drawMaps": {"thickness": th}}})
    return walls


def run(inp, out):
    os.makedirs(out, exist_ok=True)
    import infer_seg
    img = cv2.imread(inp)
    H0, W0 = img.shape[:2]
    sc = min(1.0, 1536 / max(H0, W0))
    work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
    prob = infer_seg.predict(work)
    polys = vectorize(prob)
    walls = polylines_to_walls(polys)
    ov = work.copy()
    rng = np.random.default_rng(0)
    for grp in polys:                  # colour each connected group; width = learned thickness
        col = tuple(int(c) for c in rng.integers(60, 255, 3))
        w = max(1, int(round(grp.get("thickness", 2))))
        for a, b in zip(grp["pts"], grp["pts"][1:]):
            cv2.line(ov, a, b, col, w)
    cv2.imwrite(os.path.join(out, "overlay.png"), ov)
    json.dump(walls, open(os.path.join(out, "walls.json"), "w"))
    th = [g.get("thickness", 0) for g in polys]
    m = {"input": os.path.basename(inp), "n_groups": len(polys), "n_segments": len(walls),
         "thickness_px": {"median": round(float(np.median(th)), 1) if th else 0,
                          "min": round(float(np.min(th)), 1) if th else 0,
                          "max": round(float(np.max(th)), 1) if th else 0}}
    json.dump(m, open(os.path.join(out, "metrics.json"), "w"), indent=1)
    print(json.dumps(m))
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    run(a.input, a.out)
