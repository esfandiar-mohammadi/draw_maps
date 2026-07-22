#!/usr/bin/env python
"""Build a PLANAR GRAPH of walls from the 2-channel model (wall + junctions):
nodes (points), edges (straight wall segments) with per-EDGE thickness, and node
reduction (merge collinear edges, snap close nodes) so the graph uses few nodes.
"""
import os, sys, json, argparse
from collections import defaultdict
import numpy as np, cv2
from skimage.morphology import skeletonize
# torch / segmentation_models_pytorch are imported lazily inside model()/predict()
# only — build_graph and the graph utilities are torch-free, so importing this
# module (e.g. from a torch-free ncnn inference process) stays lightweight and
# avoids the ncnn+torch OpenMP clash on some platforms.

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vectorize_walls import trace_polylines, simplify

DEV = "cuda"
IMEAN = np.array([0.485, 0.456, 0.406], np.float32)
ISTD = np.array([0.229, 0.224, 0.225], np.float32)
_m = None


def model():
    global _m
    if _m is None:
        import torch
        import segmentation_models_pytorch as smp
        ckpt = os.environ.get("WALL_GRAPH_CKPT", "pipeline/models/wall_graph_unet.pt")
        m = smp.Unet("resnet34", encoder_weights=None, classes=2).to(DEV)
        m.load_state_dict(torch.load(ckpt, map_location=DEV))
        m.eval(); _m = m
    return _m


def predict(work, tile=256):
    H, W = work.shape[:2]
    wall = np.zeros((H, W), np.float32); junc = np.zeros((H, W), np.float32); cnt = np.zeros((H, W), np.float32)
    xs = sorted(set(list(range(0, max(1, W - tile) + 1, tile)) + [max(0, W - tile)]))
    ys = sorted(set(list(range(0, max(1, H - tile) + 1, tile)) + [max(0, H - tile)]))
    for y in ys:
        for x in xs:
            crop = work[y:y + tile, x:x + tile]; ch, cw = crop.shape[:2]
            c = cv2.resize(crop, (tile, tile))
            xx = (cv2.cvtColor(c, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
            import torch
            with torch.no_grad():
                out = torch.sigmoid(model()(torch.from_numpy(xx.transpose(2, 0, 1))[None].to(DEV)))[0].cpu().numpy()
            wall[y:y + ch, x:x + cw] += cv2.resize(out[0], (tile, tile))[:ch, :cw]
            junc[y:y + ch, x:x + cw] += cv2.resize(out[1], (tile, tile))[:ch, :cw]
            cnt[y:y + ch, x:x + cw] += 1
    return wall / np.maximum(cnt, 1), junc / np.maximum(cnt, 1)


def junction_peaks(junc, thr=0.3, min_dist=6):
    m = (junc > thr).astype(np.uint8)
    n, _, _, cents = cv2.connectedComponentsWithStats(m, 8)
    return [(float(cx), float(cy)) for cx, cy in cents[1:]]


def snap(pt, nodes, r):
    for i, (nx, ny) in enumerate(nodes):
        if (pt[0] - nx) ** 2 + (pt[1] - ny) ** 2 <= r * r:
            return i
    return None


def drop_border_edges(nodes, edges, shape, margin=12):
    """Drop edges that hug the image border (both endpoints within `margin` px
    of the SAME border side) — models hallucinate a wall frame at the map edge."""
    H, W = shape[:2]
    keep = []
    for a, b, t in edges:
        (x0, y0), (x1, y1) = nodes[a], nodes[b]
        if (max(x0, x1) < margin or min(x0, x1) > W - margin
                or max(y0, y1) < margin or min(y0, y1) > H - margin):
            continue
        keep.append((a, b, t))
    return keep


def build_graph(wall, junc, wall_thr=0.4, eps=4.0, snap_r=7, min_len=8):
    binm = cv2.morphologyEx((wall > wall_thr).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    dist = cv2.distanceTransform(binm, cv2.DIST_L2, 3)
    skel = skeletonize(binm.astype(bool))
    polys = trace_polylines(skel)
    pred_nodes = junction_peaks(junc)
    nodes = list(pred_nodes)          # start from learned junctions
    edges = []                        # (i, j, thickness)

    # spatial hash so node lookup is O(1) amortised instead of O(n) per query
    # (build_graph was O(V^2) on dense organic masks -> multi-hour hang @2k px).
    cell = max(1.0, float(snap_r))
    grid = defaultdict(list)          # (cx, cy) -> [node indices]

    def _add_to_grid(i):
        nx, ny = nodes[i]
        grid[(int(nx // cell), int(ny // cell))].append(i)

    for i in range(len(nodes)):
        _add_to_grid(i)

    def node_id(pt):
        cx, cy = int(pt[0] // cell), int(pt[1] // cell)
        r2 = snap_r * snap_r
        best = None                    # lowest-index node within snap_r (matches
        for gx in (cx - 1, cx, cx + 1):   # the old linear scan's first-match rule)
            for gy in (cy - 1, cy, cy + 1):
                for i in grid.get((gx, gy), ()):
                    nx, ny = nodes[i]
                    if (pt[0] - nx) ** 2 + (pt[1] - ny) ** 2 <= r2 and (best is None or i < best):
                        best = i
        if best is None:
            nodes.append((float(pt[0]), float(pt[1]))); _add_to_grid(len(nodes) - 1)
            return len(nodes) - 1
        return best

    for p in polys:
        sp = simplify(p, eps)         # DP -> few corners
        if len(sp) < 2:
            continue
        ids = [node_id(v) for v in sp]
        for a, b, seg in zip(ids[:-1], ids[1:], zip(sp[:-1], sp[1:])):
            (x0, y0), (x1, y1) = seg
            if (x0 - x1) ** 2 + (y0 - y1) ** 2 < min_len ** 2:
                continue
            th = float(np.median([2 * dist[int(y), int(x)] for (x, y) in p
                                  if 0 <= int(y) < dist.shape[0] and 0 <= int(x) < dist.shape[1]]) or 2)
            edges.append((a, b, round(th, 1)))
    edges = drop_border_edges(nodes, edges, wall.shape)
    return merge_collinear(nodes, edges)


def merge_collinear(nodes, edges, ang_tol=12):
    """Remove degree-2 nodes whose two edges are ~collinear -> fewer nodes,
    longer edges. In-place adjacency mutation with a worklist: each merge only
    re-examines the two touched neighbours instead of rebuilding the whole degree
    map and restarting (the old break-and-restart was O(E^2) -> hung at 2k px)."""
    import math

    def ang(p, q):
        return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))

    edict = {k: [a, b, t] for k, (a, b, t) in enumerate(edges)}
    adj = defaultdict(set)            # node -> set of edge ids incident on it
    for k, (a, b, t) in edict.items():
        adj[a].add(k); adj[b].add(k)
    next_id = len(edges)
    work = [nd for nd in list(adj) if len(adj[nd]) == 2]

    while work:
        nd = work.pop()
        eks = adj[nd]
        if len(eks) != 2:
            continue
        k1, k2 = tuple(eks)
        a1, b1, t1 = edict[k1]; a2, b2, t2 = edict[k2]
        o1 = b1 if a1 == nd else a1
        o2 = b2 if a2 == nd else a2
        if o1 == nd or o2 == nd or o1 == o2:   # self-loop / would collapse -> skip
            continue
        v1 = ang(nodes[nd], nodes[o1]); v2 = ang(nodes[o2], nodes[nd])
        if abs((v1 - v2 + 180) % 360 - 180) > ang_tol:
            continue
        # collinear -> replace the two edges by a single o1--o2 edge
        del edict[k1]; del edict[k2]
        adj[o1].discard(k1); adj[o1].discard(k2)
        adj[o2].discard(k1); adj[o2].discard(k2)
        adj[nd].discard(k1); adj[nd].discard(k2)
        nk = next_id; next_id += 1
        edict[nk] = [o1, o2, round((t1 + t2) / 2, 1)]
        adj[o1].add(nk); adj[o2].add(nk)
        if len(adj[o1]) == 2:
            work.append(o1)
        if len(adj[o2]) == 2:
            work.append(o2)
    edges2 = [tuple(e) for e in edict.values()]
    used = set()
    for a, b, t in edges2:
        used.add(a); used.add(b)
    remap = {old: i for i, old in enumerate(sorted(used))}
    nodes2 = [nodes[o] for o in sorted(used)]
    edges3 = [(remap[a], remap[b], t) for a, b, t in edges2]
    return nodes2, edges3


def run(inp, out, work_edge=1536):
    os.makedirs(out, exist_ok=True)
    img = cv2.imread(inp); H, W = img.shape[:2]; sc = min(1.0, work_edge / max(H, W))
    work = cv2.resize(img, (round(W * sc), round(H * sc)), interpolation=cv2.INTER_AREA)
    wall, junc = predict(work)
    nodes, edges = build_graph(wall, junc)
    ov = (work * 0.55).astype(np.uint8)
    for a, b, t in edges:
        cv2.line(ov, tuple(map(int, nodes[a])), tuple(map(int, nodes[b])), (0, 0, 255), max(1, int(round(t))))
    for (x, y) in nodes:
        cv2.circle(ov, (int(x), int(y)), 3, (0, 255, 255), -1)
    cv2.imwrite(os.path.join(out, "graph.png"), ov)
    json.dump({"nodes": nodes, "edges": edges}, open(os.path.join(out, "graph.json"), "w"))
    ths = [t for _, _, t in edges]
    m = {"input": os.path.basename(inp), "n_nodes": len(nodes), "n_edges": len(edges),
         "thickness_px": {"median": round(float(np.median(ths)), 1) if ths else 0,
                          "min": round(float(np.min(ths)), 1) if ths else 0,
                          "max": round(float(np.max(ths)), 1) if ths else 0}}
    json.dump(m, open(os.path.join(out, "metrics.json"), "w"), indent=1)
    print(json.dumps(m))
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    run(a.input, a.out)
