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


def drop_border_edges(nodes, edges, shape, margin=12, frame_frac=0.7):
    """Drop edges that hug the image border AND span most of that side — i.e. the
    hallucinated wall FRAME at the map edge — while KEEPING short real perimeter
    walls that merely happen to sit near the border.

    An edge is a frame edge if both endpoints are within `margin` px of the SAME
    border side and its extent ALONG that side is >= frame_frac of the side length.
    frame_frac=0 restores the old behaviour (drop any border-hugging edge);
    Phase-0 diagnostic showed the old blanket rule cost ~0.05-0.12 graph recall by
    deleting real perimeter walls (INSCOPE-32)."""
    H, W = shape[:2]
    keep = []
    for a, b, t in edges:
        (x0, y0), (x1, y1) = nodes[a], nodes[b]
        drop = False
        if max(x0, x1) < margin or min(x0, x1) > W - margin:      # hugs left/right side
            drop = abs(y0 - y1) >= frame_frac * H
        elif max(y0, y1) < margin or min(y0, y1) > H - margin:    # hugs top/bottom side
            drop = abs(x0 - x1) >= frame_frac * W
        if not drop:
            keep.append((a, b, t))
    return keep


def _binarize(wall, wall_thr, low_thr=None, hyst_reach=0, close_k=3):
    """Wall mask. With low_thr: hysteresis — pixels > wall_thr are seeds that
    grow through connected pixels > low_thr, at most hyst_reach px far
    (0 = unlimited). Bridges short probability dips along a wall without
    lowering the threshold for free-standing weak blobs."""
    hi = (wall > wall_thr).astype(np.uint8)
    if low_thr is not None and low_thr < wall_thr:
        lo = (wall > low_thr).astype(np.uint8)
        if hyst_reach and hyst_reach > 0:
            k = np.ones((3, 3), np.uint8)
            cur = hi
            for _ in range(int(hyst_reach)):
                nxt = cv2.dilate(cur, k) & lo
                if np.array_equal(nxt, cur):
                    break
                cur = nxt
            hi = cur
        else:
            n, lab = cv2.connectedComponents(lo, connectivity=8)
            keep = np.zeros(n, bool)
            keep[np.unique(lab[hi > 0])] = True
            keep[0] = False
            hi = keep[lab].astype(np.uint8)
    if close_k and close_k > 1:
        hi = cv2.morphologyEx(hi, cv2.MORPH_CLOSE, np.ones((int(close_k), int(close_k)), np.uint8))
    return hi


def _contract_short(nodes, edges, shorts):
    """Contract short connector segments (a, b) into ONE node instead of dropping
    them (dropping tore a hole of up to min_len px into a continuous wall). The
    merged node sits where the member with the most long edges was."""
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    deg = defaultdict(int)
    for a, b, _ in edges:
        deg[a] += 1; deg[b] += 1
    for a, b in shorts:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    groups = defaultdict(list)
    for i in set(i for ab in shorts for i in ab):
        groups[find(i)].append(i)
    nodes = list(nodes)
    for r, mem in groups.items():
        top = max(deg[i] for i in mem)
        best = [nodes[i] for i in mem if deg[i] == top]
        nodes[r] = (float(np.mean([p[0] for p in best])), float(np.mean([p[1] for p in best])))
    out, seen = [], set()
    for a, b, t in edges:
        a, b = find(a), find(b)
        key = (min(a, b), max(a, b))
        if a == b or key in seen:
            continue
        seen.add(key)
        out.append((a, b, t))
    return nodes, out


def bridge_endpoints(nodes, edges, wall, bridge_r=32, bridge_prob=0.1, bridge_ang=30, tsnap_r=8,
                     bridge_tr=None, bridge_mr=0, bridge_mang=10):
    """Close holes at dangling (degree-1) endpoints.

    A dangling endpoint e with outward direction d is connected to
      (T)  the first other segment its ray e + t*d hits within bridge_tr, or
      (N)  the nearest point of another segment within tsnap_r (any direction), or
      (C)  a node within bridge_ang of d: another dangling end within bridge_r
           (kind "M" if that end also points back at e, else "C"), or a
           non-dangling node within bridge_tr (kind "c"),
    (bridge_tr defaults to bridge_r; T and c are the least reliable kinds, so they
    get the shorter reach; two dangling ends that face each other on one line
    within bridge_mang degrees, kind "MM", may be up to bridge_mr apart)
    whichever is shortest — but only if the MINIMUM wall probability (5x5 max
    filtered) along the new piece is >= bridge_prob, i.e. the model sees at
    least a faint wall all the way (openings where it predicts ~0 stay open).
    Radii are measured between wall FACES, not centrelines: the skeleton of a
    blob of thickness th ends ~th/2 before the blob does, so half the thickness
    of the own (and of the target) segment is added to the reach.
    The hit segment is split at the landing point so the result stays a planar
    graph with shared vertices.
    Returns (nodes, edges, bridges) with bridges = [(x0, y0, x1, y1, kind, evidence, half_thickness), ...]."""
    if not edges or (bridge_r <= 0 and tsnap_r <= 0):
        return nodes, edges, []
    nodes = [tuple(map(float, n)) for n in nodes]
    edges = [tuple(e) for e in edges]
    H, W = wall.shape
    wd = cv2.dilate(wall.astype(np.float32), np.ones((5, 5), np.uint8))   # +-2 px lateral slack

    def evidence(p, q):
        n = max(2, int(np.hypot(q[0] - p[0], q[1] - p[1])) + 1)
        xs = np.clip(np.rint(np.linspace(p[0], q[0], n)).astype(int), 0, W - 1)
        ys = np.clip(np.rint(np.linspace(p[1], q[1], n)).astype(int), 0, H - 1)
        return float(wd[ys, xs].min())

    deg = defaultdict(int)
    for a, b, _ in edges:
        deg[a] += 1; deg[b] += 1
    cos_tol = float(np.cos(np.radians(bridge_ang)))
    tr = bridge_r if bridge_tr is None else min(bridge_tr, bridge_r)
    cos_m = float(np.cos(np.radians(bridge_mang)))
    added = []
    for e in [n for n, d in list(deg.items()) if d == 1]:
        if deg[e] != 1:
            continue                                   # got connected meanwhile
        own = next(k for k, (a, b, _) in enumerate(edges) if a == e or b == e)
        o = edges[own][1] if edges[own][0] == e else edges[own][0]
        ex, ey = nodes[e]
        d = np.array([ex - nodes[o][0], ey - nodes[o][1]])
        L = float(np.hypot(*d))
        if L < 1e-6:
            continue
        d /= L
        cap = float(max(bridge_r, tsnap_r, 1))           # thickness bonus never exceeds the radius
        h_own = min(cap, 0.5 * float(edges[own][2]))
        TH = np.minimum(cap, 0.5 * np.array([t for _, _, t in edges], float))
        E = np.array([[*nodes[a], *nodes[b]] for a, b, _ in edges], float)
        A = E[:, :2]; V = E[:, 2:] - A
        skip = np.array([a == o or b == o or a == e or b == e for a, b, _ in edges])
        cands = []                                     # (length, edge idx or -1, node or -1, point)
        # (T) ray hit: e + t d = A + s V
        den = d[0] * V[:, 1] - d[1] * V[:, 0]
        ok = np.abs(den) > 1e-9
        den_s = np.where(ok, den, 1.0)
        w = A - [ex, ey]
        t = (w[:, 0] * V[:, 1] - w[:, 1] * V[:, 0]) / den_s
        s = (w[:, 0] * d[1] - w[:, 1] * d[0]) / den_s
        hit = ok & ~skip & (t > 0) & (t <= tr + h_own + TH) & (s >= 0) & (s <= 1)
        hit &= bridge_r > 0
        if hit.any():
            k = int(np.where(hit, t, np.inf).argmin())
            cands.append((float(t[k]), k, -1, (ex + t[k] * d[0], ey + t[k] * d[1]), "T"))
        # (N) nearest point on another segment
        if tsnap_r > 0:
            L2 = np.maximum((V ** 2).sum(1), 1e-9)
            u = np.clip(-(w * V).sum(1) / L2, 0, 1)
            Q = A + u[:, None] * V
            dist = np.where(skip, np.inf, np.hypot(Q[:, 0] - ex, Q[:, 1] - ey))
            dist = dist - TH
            k = int(dist.argmin())
            if dist[k] <= tsnap_r + h_own:
                cands.append((float(dist[k] + TH[k]), k, -1, (float(Q[k, 0]), float(Q[k, 1])), "N"))
        # (C) node ahead within the cone
        if bridge_r > 0:
            nth = {}; ndir = {}
            for a, b, tk in edges:
                for n, m_ in ((a, b), (b, a)):
                    if deg[n] == 1:
                        nth[n] = min(cap, 0.5 * float(tk))
                        ndir[n] = (nodes[n][0] - nodes[m_][0], nodes[n][1] - nodes[m_][1])
            for n in deg:
                if n == e or n == o or deg[n] == 0:
                    continue
                vx, vy = nodes[n][0] - ex, nodes[n][1] - ey
                dn = float(np.hypot(vx, vy))
                if dn < 1e-6:
                    continue
                cf = (vx * d[0] + vy * d[1]) / dn       # e looks at n
                kind, reach = "c", tr
                if deg[n] == 1:
                    ox, oy = ndir[n]
                    cb = -(ox * vx + oy * vy) / ((float(np.hypot(ox, oy)) or 1.0) * dn)   # n looks back at e
                    kind, reach = ("M" if cb >= cos_tol else "C"), bridge_r
                    if bridge_mr > bridge_r and cf >= cos_m and cb >= cos_m:
                        kind, reach = "MM", bridge_mr   # two wall ends facing each other on one line
                if dn <= reach + h_own + nth.get(n, 0.0) and cf >= cos_tol:
                    cands.append((dn, -1, n, nodes[n], kind))
        for ln, k, n, q, kind in sorted(cands, key=lambda c: c[0]):
            ev = evidence((ex, ey), q)
            if ev < bridge_prob:
                continue
            th = edges[own][2]
            if n < 0:                                  # landed on segment k
                a, b, tk = edges[k]
                da = np.hypot(q[0] - nodes[a][0], q[1] - nodes[a][1])
                db = np.hypot(q[0] - nodes[b][0], q[1] - nodes[b][1])
                if min(da, db) <= 3.0:
                    n = a if da <= db else b           # reuse the close end node
                else:
                    nodes.append((float(q[0]), float(q[1]))); n = len(nodes) - 1
                    edges[k] = (a, n, tk); edges.append((n, b, tk))
                    deg[n] += 2
            if n == e or any({a, b} == {e, n} for a, b, _ in edges):
                continue
            edges.append((e, n, th)); deg[e] += 1; deg[n] += 1
            added.append((ex, ey, float(nodes[n][0]), float(nodes[n][1]), kind, ev, h_own))
            break
    return nodes, edges, added


# Keyword presets for build_graph (benchmark: pipeline/gap_eval.py, 32 in-scope FA maps,
# ConvNeXt-Tiny student, wall_thr 0.5, long edge 1024):
#   LEGACY  the vectorizer as it was before the hole fixes (graph-F1 0.765, P 0.815).
#   (defaults)  bug fixes only: F1 0.765 / P 0.815, holes < 15 px 448 -> 414.
#   SEAL    defaults + closing of dangling wall ends. Holes < 15 px 448 -> 330, 15-40 px
#           436 -> 361, near-miss dangling ends 1423 -> 549, at P 0.815 -> 0.809,
#           F1 0.765 -> 0.763, +6 % segments, and more doors walled over (0.65 -> 0.72);
#           ~40 % of the added length is not on a GT wall (e.g. links between furniture).
#           A real trade-off, therefore NOT the default: build_graph(w, j, **SEAL).
# All radii are px of the probability map (reference: long edge 1024).
LEGACY = dict(connect_short=False, close_loops=False, join_ends=False, merge_dev=None)
SEAL = dict(bridge_r=32, bridge_tr=16, bridge_mr=48, bridge_prob=0.1, tsnap_r=8)


def build_graph(wall, junc, wall_thr=0.4, eps=4.0, snap_r=7, min_len=8, border_margin=12,
                connect_short=True, low_thr=None, hyst_reach=0, close_k=3,
                bridge_r=0, bridge_prob=0.1, bridge_ang=30, tsnap_r=0, bridge_tr=None,
                bridge_mr=0, bridge_mang=10,
                merge_ang=12, merge_dev=2, close_loops=True, join_ends=True, info=None):
    """Probability maps -> planar wall graph (nodes, edges with thickness).

    Hole fixes that are ON by default (free on the benchmark):
      connect_short  segments shorter than min_len that CONNECT two nodes are
                     contracted into one node (True) or kept ("keep") instead of
                     dropped (False = legacy; tore holes into continuous walls).
      close_loops    re-append the closing vertex of a closed skeleton loop
                     (approxPolyDP(closed=True) drops it -> one side missing).
      join_ends      polylines leaving the same skeleton junction share ONE node.
      merge_dev      max distance (px) an absorbed vertex may end up from a merged
                     collinear edge (None = unlimited = legacy: curves became
                     chords that leave the wall).
    Hole closing that is OFF by default (precision trade-off, see SEAL):
      bridge_r, bridge_tr, tsnap_r, bridge_prob, bridge_ang  see bridge_endpoints.
    Rejected on the benchmark, kept only for experiments (leave at defaults):
      low_thr, hyst_reach  hysteresis binarization (precision 0.815 -> 0.74-0.79);
      close_k > 3          larger morphological closing (F1 -0.001 .. -0.006).
    info: optional dict, receives info["bridges"] (the added pieces).
    """
    binm = _binarize(wall, wall_thr, low_thr, hyst_reach, close_k)
    dist = cv2.distanceTransform(binm, cv2.DIST_L2, 3)
    skel = skeletonize(binm.astype(bool))
    polys = trace_polylines(skel)
    pred_nodes = junction_peaks(junc)
    nodes = list(pred_nodes)          # start from learned junctions
    edges = []                        # (i, j, thickness)
    shorts = []                       # short connector segments (i, j)
    ends = []                         # (x, y, node) of every traced polyline end

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
        if close_loops and len(p) > 2 and p[0] == p[-1] and sp[0] != sp[-1]:
            sp = list(sp) + [sp[0]]   # approxPolyDP(closed=True) drops the closing vertex
        ids = [node_id(v) for v in sp]
        ends.append((p[0][0], p[0][1], ids[0])); ends.append((p[-1][0], p[-1][1], ids[-1]))
        th = None
        for a, b, seg in zip(ids[:-1], ids[1:], zip(sp[:-1], sp[1:])):
            (x0, y0), (x1, y1) = seg
            if (x0 - x1) ** 2 + (y0 - y1) ** 2 < min_len ** 2:
                if connect_short and a != b:
                    if connect_short == "keep":
                        edges.append((a, b, 2.0))
                    else:
                        shorts.append((a, b))
                continue
            if th is None:
                th = float(np.median([2 * dist[int(y), int(x)] for (x, y) in p
                                      if 0 <= int(y) < dist.shape[0] and 0 <= int(x) < dist.shape[1]]) or 2)
            edges.append((a, b, round(th, 1)))
    if join_ends:
        # polylines leaving the same skeleton junction start on ADJACENT pixels but
        # can snap to different nodes (one to a junction peak <= snap_r away, the
        # other not) -> a hole of a few px exactly at the junction. Tie them.
        eh = defaultdict(list)
        for x, y, i in ends:
            eh[(int(x) // 3, int(y) // 3)].append((x, y, i))
        for (cx, cy), lst in list(eh.items()):
            for x, y, i in lst:
                for gx in (cx - 1, cx, cx + 1):
                    for gy in (cy - 1, cy, cy + 1):
                        for x2, y2, j in eh.get((gx, gy), ()):
                            if j != i and abs(x - x2) <= 2 and abs(y - y2) <= 2:
                                shorts.append((i, j))
    if shorts:
        nodes, edges = _contract_short(nodes, edges, shorts)
    if border_margin > 0:
        edges = drop_border_edges(nodes, edges, wall.shape, margin=border_margin)
    nodes, edges = merge_collinear(nodes, edges, merge_ang, merge_dev)
    if bridge_r > 0 or tsnap_r > 0:
        nodes, edges, br = bridge_endpoints(nodes, edges, wall, bridge_r, bridge_prob, bridge_ang, tsnap_r, bridge_tr,
                                             bridge_mr, bridge_mang)
        if info is not None:
            info["bridges"] = br
        if br:
            nodes, edges = merge_collinear(nodes, edges, merge_ang, merge_dev)
    return nodes, edges


def merge_collinear(nodes, edges, ang_tol=12, dev_tol=None):
    """Remove degree-2 nodes whose two edges are ~collinear -> fewer nodes,
    longer edges. dev_tol (px): a merge is refused if any node absorbed into the
    new edge would end up farther than dev_tol from it — without it a chain of
    individually-small turns (a curve) is merged step by step into a chord that
    leaves the wall. In-place adjacency mutation with a worklist: each merge only
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
    via = defaultdict(list)           # edge id -> coords of nodes absorbed into it
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
        if dev_tol is not None:
            pts = np.array(via[k1] + via[k2] + [nodes[nd]], float)
            p0 = np.array(nodes[o1], float); v = np.array(nodes[o2], float) - p0
            ln = float(np.hypot(*v))
            if ln < 1e-6 or np.abs((pts[:, 0] - p0[0]) * v[1] - (pts[:, 1] - p0[1]) * v[0]).max() / ln > dev_tol:
                continue
        # collinear -> replace the two edges by a single o1--o2 edge
        del edict[k1]; del edict[k2]
        adj[o1].discard(k1); adj[o1].discard(k2)
        adj[o2].discard(k1); adj[o2].discard(k2)
        adj[nd].discard(k1); adj[nd].discard(k2)
        nk = next_id; next_id += 1
        if dev_tol is not None:
            via[nk] = via.pop(k1, []) + via.pop(k2, []) + [nodes[nd]]
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
