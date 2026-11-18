#!/usr/bin/env python
"""Gap ("hole in a wall") benchmark for the wall vectorizer.

The graph-F1 of graph_eval_student.py uses a square tolerance band, so a hole
shorter than 2*tol ALONG a wall is invisible to it. This script measures holes
directly, on the same maps / prediction path / reference scale (long edge 1024).

Metrics (all at the 1024 reference scale, tol = max(4, 0.4*grid_px) as graph-F1):
  cov      GT-wall coverage by length. GT walls are sampled every 1 px; a sample
           is covered iff a predicted segment crosses its NORMAL ray within
           +-tol (perpendicular tolerance only -> holes along the wall count);
           within tol of a GT corner/junction the plain distance <= tol counts
           (corner closure is judged by dnear / sealed instead).
  holes    maximal uncovered GT runs (>= MIN_GAP px, chained across GT vertices)
           that are bounded by covered GT wall at >= 2 distinct ends = a hole in
           an otherwise detected wall. Bucketed S <15 px, M 15-40 px, L >40 px.
  endgaps  uncovered runs with exactly 1 covered end (wall stops short).
  missed   uncovered runs with no covered end (wall not detected at all).
  sealed   GT rooms (regions enclosed by GT walls+doors, >= 1 grid cell) that are
           still enclosed by the PREDICTED walls (+ GT doors as plugs): the
           region around the room centre must not reach the image border nor
           grow beyond 1.5x the GT room area. One hole unseals a room.
  dangle   predicted degree-1 endpoints; dnear = those with another predicted
           segment within NEAR px (unclosed T-junction / collinear near miss).
  P/R/F1   the unchanged graph-F1 protocol; nseg / len = segment count / length.
  GT-free fidelity of the predicted segments (vs the model's own output):
  lowp     share of predicted length on wall probability < 0.2 (5x5 max) =
           "shortcut" pieces crossing floor; nlowseg = #segments whose mean
           probability is < 0.3 or that have > 30 % of such pixels.
  skdev    mean distance (px) of predicted segments from the mask skeleton at
           wall_thr; dev3 / dev6 = share of length > 3 / > 6 px off the skeleton
           (chords cutting corners, zigzags).

Usage:
  # 1) cache probability maps once (inference, slow):
  python pipeline/gap_eval.py --cache_dir DIR --build_cache \
      --ckpt pipeline/models/wall_student_convnext_tiny.onnx --scales 1024
  # 2) evaluate build_graph variants from the cache (seconds):
  python pipeline/gap_eval.py --cache_dir DIR --wall_thr 0.5 \
      --variants "base:legacy=1;new:"  [--per_map] [--overlay_dir OUT]
A variant is name:key=value,key=value (kwargs for graph_infer.build_graph);
legacy=1 / seal=1 expand to graph_infer.LEGACY / graph_infer.SEAL.
"""
import os, sys, json, time, argparse
from collections import defaultdict
from multiprocessing import Pool
import numpy as np, cv2
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graph_infer

MIN_GAP = 3          # px; shorter uncovered runs are GT/prediction jitter
BUCKETS = (15, 40)   # px at ref scale: S < 15 <= M < 40 <= L
NEAR = 15            # px; "near-miss" radius for dangling endpoints
LEGACY = dict(graph_infer.LEGACY, low_thr=None, bridge_r=0, tsnap_r=0)


# ----------------------------------------------------------------- cache
def build_cache(a):
    from uvtt import load as load_uvtt
    import graph_eval_student as ges
    os.makedirs(a.cache_dir, exist_ok=True)
    scales = [int(x) for x in a.scales.split(",")]
    for s in [ln.strip() for ln in open(a.fa_list) if ln.strip()]:
        out = os.path.join(a.cache_dir, s + ".npz")
        if os.path.exists(out):
            continue
        r = load_uvtt(os.path.join("corpus/fa", s + ".dd2vtt"))
        if r["image"] is None or not r["walls"]:
            print("SKIP", s, flush=True)
            continue
        t0 = time.time()
        wall, junc, sc = ges.ms_predict(r["image"], scales, a.ckpt, a.encoder)
        RH, RW = wall.shape
        img = cv2.resize(r["image"], (RW, RH), interpolation=cv2.INTER_AREA)
        np.savez_compressed(
            out + ".tmp.npz", wall=wall, junc=junc, sc=sc, ppg=r["ppg"],
            walls=np.array(r["walls"], np.float64).reshape(-1, 4) * sc,
            doors=np.array(r["doors"], np.float64).reshape(-1, 4) * sc,
            img=cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1])
        os.replace(out + ".tmp.npz", out)
        print(f"cached {s} {RW}x{RH} {time.time() - t0:.1f}s", flush=True)


# --------------------------------------------------------------- geometry
def raster(segs, shape, thick=1):
    m = np.zeros(shape, np.uint8)
    for x0, y0, x1, y1 in segs:
        cv2.line(m, (int(x0), int(y0)), (int(x1), int(y1)), 255, thick)
    return m > 0


def dil(mask, tol):
    k = 2 * int(tol) + 1
    return cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0


def sample_segs(segs):
    """1-px samples along every segment -> (xy, normal, seg_slices)."""
    P, N, sl = [], [], []
    n = 0
    for x0, y0, x1, y1 in segs:
        L = float(np.hypot(x1 - x0, y1 - y0))
        k = max(2, int(round(L)) + 1)
        t = np.linspace(0, 1, k)[:, None]
        P.append(np.array([[x0, y0]]) + t * np.array([[x1 - x0, y1 - y0]]))
        nv = np.array([-(y1 - y0), x1 - x0]) / max(L, 1e-6)
        N.append(np.repeat(nv[None], k, 0))
        sl.append((n, n + k)); n += k
    if not P:
        return np.zeros((0, 2)), np.zeros((0, 2)), []
    return np.concatenate(P), np.concatenate(N), sl


def ray_max(img, P, N, tol):
    """max of img along the normal ray +-tol at every sample."""
    H, W = img.shape
    best = np.zeros(len(P), img.dtype if img.dtype != bool else np.uint8)
    for k in range(-int(tol), int(tol) + 1):
        x = np.rint(P[:, 0] + k * N[:, 0]).astype(int)
        y = np.rint(P[:, 1] + k * N[:, 1]).astype(int)
        ok = (x >= 0) & (x < W) & (y >= 0) & (y < H)
        v = np.zeros_like(best)
        v[ok] = img[y[ok], x[ok]]
        best = np.maximum(best, v)
    return best


def gt_runs(segs, sl, covered):
    """Uncovered runs chained across GT vertices.
    -> list of dict(idx=sample indices, ends=#distinct covered ends)."""
    n = len(covered)
    rows, cols = [], []
    node_samples = defaultdict(list)
    for (x0, y0, x1, y1), (a, b) in zip(segs, sl):
        rows += list(range(a, b - 1)); cols += list(range(a + 1, b))
        node_samples[(int(round(x0)), int(round(y0)))].append(a)
        node_samples[(int(round(x1)), int(round(y1)))].append(b - 1)
    samp_node = {}
    for key, ss in node_samples.items():
        for i in ss:
            samp_node.setdefault(i, []).append(key)
        for i in range(len(ss)):
            for j in range(i + 1, len(ss)):
                rows.append(ss[i]); cols.append(ss[j])
    rows = np.array(rows, int); cols = np.array(cols, int)
    unc = ~covered
    both = unc[rows] & unc[cols]
    g = coo_matrix((np.ones(both.sum(), np.uint8), (rows[both], cols[both])), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    ends = defaultdict(set)
    mixed = unc[rows] != unc[cols]
    for r, c in zip(rows[mixed], cols[mixed]):
        u, v = (r, c) if unc[r] else (c, r)         # u uncovered, v covered
        shared = set(samp_node.get(u, ())) & set(samp_node.get(v, ()))
        ends[lab[u]].add(("node", min(shared)) if shared else ("seg", int(v)))
    runs = defaultdict(list)
    for i in np.where(unc)[0]:
        runs[lab[i]].append(i)
    return [dict(idx=np.array(ix), ends=len(ends.get(k, ()))) for k, ix in runs.items()]


def near_corner(segs, sl, tol):
    """bool per sample: within tol (along its segment) of a GT vertex that is a
    corner (turn > 15 deg) or a junction (degree >= 3)."""
    inc = defaultdict(list)
    for i, (x0, y0, x1, y1) in enumerate(segs):
        d = np.array([x1 - x0, y1 - y0], float); d /= max(np.hypot(*d), 1e-6)
        inc[(int(round(x0)), int(round(y0)))].append(d)
        inc[(int(round(x1)), int(round(y1)))].append(-d)

    def corner(key):
        ds = inc[key]
        if len(ds) == 1:
            return False
        return len(ds) >= 3 or float(ds[0] @ ds[1]) > -np.cos(np.radians(15))

    out = np.zeros(sl[-1][1] if sl else 0, bool)
    for (x0, y0, x1, y1), (a, b) in zip(segs, sl):
        k = min(b - a, int(tol) + 1)
        if corner((int(round(x0)), int(round(y0)))):
            out[a:a + k] = True
        if corner((int(round(x1)), int(round(y1)))):
            out[b - k:b] = True
    return out


def seg_point_dist(P, segs):
    """min distance of every point in P (n,2) to a set of segments (m,4)."""
    if len(segs) == 0 or len(P) == 0:
        return np.full(len(P), np.inf)
    best = np.full(len(P), np.inf)
    for x0, y0, x1, y1 in segs:
        d = np.array([x1 - x0, y1 - y0]); L2 = float(d @ d) or 1e-9
        t = np.clip(((P - [x0, y0]) @ d) / L2, 0, 1)
        best = np.minimum(best, np.hypot(*(P - ([x0, y0] + t[:, None] * d)).T))
    return best


def dangling(nodes, edges):
    """degree-1 endpoints and how many have a foreign segment within NEAR px."""
    deg = defaultdict(int)
    for a, b, _ in edges:
        deg[a] += 1; deg[b] += 1
    ends = [n for n, d in deg.items() if d == 1]
    near = 0
    E = np.array([[*nodes[a], *nodes[b]] for a, b, _ in edges], float).reshape(-1, 4)
    for n in ends:
        other = np.array([i for i, (a, b, _) in enumerate(edges) if a != n and b != n], int)
        if len(other) and seg_point_dist(np.array([nodes[n]], float), E[other])[0] <= NEAR:
            near += 1
    return len(ends), near


def sealed_rooms(gt_segs, doors, pred_segs, shape, tol, cell):
    H, W = shape
    gtm = raster(list(gt_segs) + list(doors), shape)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((~gtm).astype(np.uint8), 4)
    pm = raster(pred_segs, shape) | raster(doors, shape, thick=2 * int(tol) + 1)
    pn, plab, pstats, _ = cv2.connectedComponentsWithStats((~pm).astype(np.uint8), 4)
    dt = cv2.distanceTransform((~gtm).astype(np.uint8), cv2.DIST_L2, 3)
    tot = ok = 0
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x == 0 or y == 0 or x + w >= W or y + h >= H or area < cell * cell:
            continue
        d = np.where(lab == i, dt, 0)
        ay, ax = np.unravel_index(int(d.argmax()), d.shape)
        if d[ay, ax] < tol + 2 or pm[ay, ax]:
            continue
        tot += 1
        j = plab[ay, ax]
        px, py, pw, ph, parea = pstats[j]
        border = px == 0 or py == 0 or px + pw >= W or py + ph >= H
        ok += int(not border and parea <= 1.5 * area)
    return tot, ok


# ------------------------------------------------------------------ eval
def load_map(cache_dir, slug):
    d = np.load(os.path.join(cache_dir, slug + ".npz"))
    return dict(slug=slug, wall=d["wall"], junc=d["junc"], sc=float(d["sc"]), ppg=float(d["ppg"]),
                walls=d["walls"], doors=d["doors"], img=d["img"])


def evaluate(m, kw, wall_thr, overlay=None, detail=False):
    wall, junc = m["wall"], m["junc"]
    shape = wall.shape
    t0 = time.time()
    info = {}
    nodes, edges = graph_infer.build_graph(wall, junc, wall_thr=wall_thr, info=info, **kw)
    dt = time.time() - t0
    pred_segs = [(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]) for a, b, t in edges]
    gt_segs = [tuple(s) for s in m["walls"]]
    tol = max(4, 0.4 * m["ppg"] * m["sc"])
    gt = raster(gt_segs, shape); pred = raster(pred_segs, shape)
    out = dict(slug=m["slug"], nseg=len(edges), time=dt,
               len=float(sum(np.hypot(x1 - x0, y1 - y0) for x0, y0, x1, y1 in pred_segs)))
    if pred.sum():
        P = float((pred & dil(gt, tol)).sum()) / float(pred.sum())
        R = float((gt & dil(pred, tol)).sum()) / float(gt.sum())
    else:
        P = R = 0.0
    out.update(P=P, R=R, F1=2 * P * R / (P + R + 1e-9))
    # normal-ray coverage + runs
    S, N, sl = sample_segs(gt_segs)
    predd = cv2.dilate(pred.astype(np.uint8), np.ones((3, 3), np.uint8))
    covered = ray_max(predd, S, N, tol) > 0
    # corner slack: a predicted corner may sit up to tol off the GT corner, which
    # leaves the last <= tol px of a GT segment without a normal-ray hit although
    # nothing is open. Near GT corners/junctions fall back to the disc criterion.
    pdt = cv2.distanceTransform((~pred).astype(np.uint8), cv2.DIST_L2, 5)
    xi = np.clip(np.rint(S[:, 0]).astype(int), 0, shape[1] - 1)
    yi = np.clip(np.rint(S[:, 1]).astype(int), 0, shape[0] - 1)
    covered |= near_corner(gt_segs, sl, tol) & (pdt[yi, xi] <= tol)
    out["cov"] = float(covered.mean())
    runs = [r for r in gt_runs(gt_segs, sl, covered) if len(r["idx"]) >= MIN_GAP]
    binm = cv2.morphologyEx((wall > wall_thr).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    mask_hit = ray_max(binm, S, N, tol) > 0
    if "skel" not in m:
        from skimage.morphology import skeletonize
        m["skel"] = skeletonize(binm.astype(bool)).astype(np.uint8)
    sk_hit = ray_max(cv2.dilate(m["skel"], np.ones((3, 3), np.uint8)), S, N, tol) > 0
    prob = ray_max(wall, S, N, tol)
    ddoor = seg_point_dist(S, m["doors"])
    for k in ("holeS", "holeM", "holeL", "endgap", "missed", "hole_px", "endgap_px", "missed_px"):
        out[k] = 0
    holes = []
    for r in runs:
        L = len(r["idx"])
        if r["ends"] >= 2:
            b = "S" if L < BUCKETS[0] else "M" if L < BUCKETS[1] else "L"
            out["hole" + b] += 1; out["hole_px"] += L
            mh = float(mask_hit[r["idx"]].mean())
            cause = ("door" if ddoor[r["idx"]].min() <= tol else
                     "vectorizer" if float(sk_hit[r["idx"]].mean()) >= 0.8 else
                     "offcentre" if mh >= 0.8 else
                     "weakprob" if float((prob[r["idx"]] >= 0.2).mean()) >= 0.8 else "nopred")
            holes.append(dict(len=L, bucket=b, cause=cause, mask_frac=mh,
                              pmin=float(prob[r["idx"]].min()),
                              xy=[float(v) for v in S[r["idx"]].mean(0)]))
        elif r["ends"] == 1:
            out["endgap"] += 1; out["endgap_px"] += L
        else:
            out["missed"] += 1; out["missed_px"] += L
    out["gt_px"] = len(S)
    out["holes"] = holes
    out["dangle"], out["dnear"] = dangling(nodes, edges)
    out["rooms"], out["sealed"] = sealed_rooms(gt_segs, m["doors"], pred_segs, shape, tol, m["ppg"] * m["sc"])
    # doors: how much of the GT door length does the prediction wall off?
    if len(m["doors"]):
        DS, DN, _ = sample_segs([tuple(s) for s in m["doors"]])
        dc = ray_max(predd, DS, DN, tol) > 0
        out["door_px"] = len(DS); out["door_cov_px"] = int(dc.sum())
        out["door_prob"] = float(ray_max(wall, DS, DN, tol).mean())
    else:
        out["door_px"] = out["door_cov_px"] = 0; out["door_prob"] = float("nan")
    out["wall_prob"] = float(prob.mean())
    # bridge audit: where do the pieces ADDED by bridge_endpoints lie?
    br = info.get("bridges", [])
    out["nbr"] = len(br); out["br_px"] = out["br_gt_px"] = out["br_door_px"] = out["br_false_px"] = 0
    out["nbr_false"] = 0
    out["bridges"] = []
    if br:
        for sgm in br:
            bs, _, _ = sample_segs([sgm[:4]])
            bw = seg_point_dist(bs, m["walls"]); bd = seg_point_dist(bs, m["doors"])
            ng = int((bw <= tol).sum()); nd = int(((bw > tol) & (bd <= tol)).sum()); nf = len(bs) - ng - nd
            out["br_px"] += len(bs); out["br_gt_px"] += ng; out["br_door_px"] += nd; out["br_false_px"] += nf
            out["nbr_false"] += int(nf > 0.5 * len(bs))
            out["bridges"].append([*map(float, sgm[:4]), ng, nd, nf, *sgm[4:]])
    # precision audit by length: predicted px not near any GT wall nor door
    ps, _, _ = sample_segs(pred_segs)
    if len(ps):
        dw = seg_point_dist(ps, m["walls"]) if len(ps) * len(m["walls"]) < 4e7 else None
        if dw is None:
            dtm = cv2.distanceTransform((~gt).astype(np.uint8), cv2.DIST_L2, 5)
            xi = np.clip(np.rint(ps[:, 0]).astype(int), 0, shape[1] - 1)
            yi = np.clip(np.rint(ps[:, 1]).astype(int), 0, shape[0] - 1)
            dw = dtm[yi, xi]
        dd = seg_point_dist(ps, m["doors"])
        out["pred_on_door_px"] = int(((dw > tol) & (dd <= tol)).sum())
        out["pred_false_px"] = int(((dw > tol) & (dd > tol)).sum())
        # GT-free support / fidelity: does the segment run where the model sees a wall?
        if "skdt" not in m:
            m["skdt"] = cv2.distanceTransform((m["skel"] == 0).astype(np.uint8), cv2.DIST_L2, 5)
            m["wd"] = cv2.dilate(wall, np.ones((5, 5), np.uint8))
        xi = np.clip(np.rint(ps[:, 0]).astype(int), 0, shape[1] - 1)
        yi = np.clip(np.rint(ps[:, 1]).astype(int), 0, shape[0] - 1)
        pv = m["wd"][yi, xi]; sd = m["skdt"][yi, xi]
        out["pred_px"] = len(ps)
        out["lowp_px"] = int((pv < 0.2).sum())
        out["skdev_sum"] = float(sd.sum()); out["skdev_gt3"] = int((sd > 3).sum())
        out["skdev_gt6"] = int((sd > 6).sum())
        nlow = 0; n0 = 0
        for x0, y0, x1, y1 in pred_segs:
            k = max(2, int(round(float(np.hypot(x1 - x0, y1 - y0)))) + 1)
            if float(pv[n0:n0 + k].mean()) < 0.3 or float((pv[n0:n0 + k] < 0.2).mean()) > 0.3:
                nlow += 1
            n0 += k
        out["nlowseg"] = nlow
    else:
        out["pred_on_door_px"] = out["pred_false_px"] = 0
        out["pred_px"] = out["lowp_px"] = out["skdev_gt3"] = out["skdev_gt6"] = out["nlowseg"] = 0
        out["skdev_sum"] = 0.0
    if detail:
        out["nodes"] = nodes; out["edges"] = edges
    if overlay:
        img = cv2.imdecode(m["img"], cv2.IMREAD_COLOR)
        ov = (img * 0.55).astype(np.uint8)
        for x0, y0, x1, y1 in gt_segs:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 255, 0), 1)
        for x0, y0, x1, y1 in m["doors"]:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (255, 160, 0), 2)
        for x0, y0, x1, y1 in pred_segs:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 1)
        for (x, y) in nodes:
            cv2.circle(ov, (int(x), int(y)), 2, (0, 255, 255), -1)
        for b in out["bridges"]:                     # added pieces: magenta (false: white core)
            cv2.line(ov, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (255, 0, 255), 2)
            if b[6] > 0.5 * (b[4] + b[5] + b[6]):
                cv2.line(ov, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (255, 255, 255), 1)
        col = dict(vectorizer=(255, 0, 255), offcentre=(255, 255, 0), weakprob=(0, 165, 255), nopred=(255, 255, 255), door=(255, 160, 0))
        for h in holes:
            cv2.circle(ov, (int(h["xy"][0]), int(h["xy"][1])), 7, col[h["cause"]], 1)
        cv2.imwrite(overlay, ov)
    return out


def image_mode(a):
    """GT-free check on one image (same path as wall_service.detect)."""
    import graph_eval_student as ges
    from skimage.morphology import skeletonize
    img = cv2.imread(a.image)
    npz = a.image_cache or ""
    if npz and os.path.exists(npz):
        d = np.load(npz); wall, junc, sc = d["wall"], d["junc"], float(d["sc"])
    else:
        wall, junc, sc = ges.ms_predict(img, [int(x) for x in a.scales.split(",")], a.ckpt, a.encoder)
        if npz:
            np.savez_compressed(npz, wall=wall, junc=junc, sc=sc)
    shape = wall.shape
    binm = cv2.morphologyEx((wall > a.wall_thr).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    skdt = cv2.distanceTransform((~skeletonize(binm.astype(bool))).astype(np.uint8), cv2.DIST_L2, 5)
    wd = cv2.dilate(wall, np.ones((5, 5), np.uint8))
    print(f"{'variant':22s} {'nseg':>6s} {'len':>7s} {'dangle':>6s} {'dnear':>6s} {'lowp':>6s} {'nlowseg':>7s} "
          f"{'skdev':>6s} {'dev3':>6s} {'dev6':>6s} {'time':>6s}")
    for name, kw in parse_variants(a.variants):
        t0 = time.time()
        nodes, edges = graph_infer.build_graph(wall, junc, wall_thr=a.wall_thr, **kw)
        dt = time.time() - t0
        segs = [(nodes[i][0], nodes[i][1], nodes[j][0], nodes[j][1]) for i, j, _ in edges]
        ps, _, sl = sample_segs(segs)
        xi = np.clip(np.rint(ps[:, 0]).astype(int), 0, shape[1] - 1)
        yi = np.clip(np.rint(ps[:, 1]).astype(int), 0, shape[0] - 1)
        pv = wd[yi, xi]; sd = skdt[yi, xi]
        low = [(float(pv[i:j].mean()) < 0.3 or float((pv[i:j] < 0.2).mean()) > 0.3) for i, j in sl]
        dg, dn = dangling(nodes, edges)
        print(f"{name:22s} {len(edges):6d} {sum(np.hypot(x1 - x0, y1 - y0) for x0, y0, x1, y1 in segs):7.0f} "
              f"{dg:6d} {dn:6d} {(pv < 0.2).mean():6.3f} {sum(low):7d} {sd.mean():6.3f} "
              f"{(sd > 3).mean():6.3f} {(sd > 6).mean():6.3f} {dt:6.2f}", flush=True)
        if a.out:
            deg = defaultdict(int)
            for i, j, _ in edges:
                deg[i] += 1; deg[j] += 1
            ov = img.copy()
            if a.show_prob:
                pm = cv2.resize(wall, (img.shape[1], img.shape[0]))
                ov = (ov * 0.4).astype(np.uint8)
                ov[..., 1] = np.maximum(ov[..., 1], (pm * 200).astype(np.uint8))
            for (x0, y0, x1, y1), lw in zip(segs, low):
                cv2.line(ov, (int(x0 / sc), int(y0 / sc)), (int(x1 / sc), int(y1 / sc)),
                         (0, 0, 255) if lw else (0, 255, 255), 3, cv2.LINE_AA)
            for i, (x, y) in enumerate(nodes):
                cv2.circle(ov, (int(x / sc), int(y / sc)), 5 if deg[i] == 1 else 3,
                           (255, 0, 255) if deg[i] == 1 else (255, 255, 255), -1)
            base, ext = os.path.splitext(a.out)
            cv2.imwrite(a.out if len(parse_variants(a.variants)) == 1 else f"{base}_{name}{ext}", ov)


_MAPS = {}


def _job(arg):
    cache_dir, slug, name, kw, wall_thr, ovdir = arg
    if slug not in _MAPS:
        _MAPS[slug] = load_map(cache_dir, slug)
    ov = os.path.join(ovdir, f"{slug}__{name}.png") if ovdir else None
    r = evaluate(_MAPS[slug], kw, wall_thr, overlay=ov)
    r["variant"] = name
    return r


def parse_variants(spec):
    out = []
    for part in [p for p in spec.split(";") if p.strip()]:
        name, _, kv = part.partition(":")
        kw = {}
        for item in [i for i in kv.split(",") if i.strip()]:
            k, v = item.split("=")
            if k == "legacy":
                kw.update(LEGACY); continue
            if k == "seal":
                kw.update(graph_infer.SEAL); continue
            try:
                kw[k] = None if v == "None" else (v == "True") if v in ("True", "False") else \
                    int(v) if v.lstrip("-").isdigit() else float(v)
            except ValueError:
                kw[k] = v
        out.append((name.strip(), kw))
    return out


def summarize(rs):
    n = len(rs)
    s = lambda k: sum(r[k] for r in rs)          # noqa: E731
    mean = lambda k: sum(r[k] for r in rs) / n   # noqa: E731
    return dict(F1=mean("F1"), P=mean("P"), R=mean("R"), cov=mean("cov"),
                holeS=s("holeS"), holeM=s("holeM"), holeL=s("holeL"), endgap=s("endgap"),
                missed=s("missed"), dangle=s("dangle"), dnear=s("dnear"),
                sealed=s("sealed"), rooms=s("rooms"), nseg=s("nseg"), len=s("len"),
                door_cov=s("door_cov_px") / max(1, s("door_px")),
                ondoor=s("pred_on_door_px"), false_px=s("pred_false_px"), time=mean("time"),
                lowp=s("lowp_px") / max(1, s("pred_px")), nlowseg=s("nlowseg"),
                skdev=s("skdev_sum") / max(1, s("pred_px")), dev3=s("skdev_gt3") / max(1, s("pred_px")),
                dev6=s("skdev_gt6") / max(1, s("pred_px")),
                nbr=s("nbr"), brF=s("nbr_false"), br_px=s("br_px"), br_gt=s("br_gt_px") / max(1, s("br_px")),
                br_door=s("br_door_px") / max(1, s("br_px")), br_false=s("br_false_px") / max(1, s("br_px")))


HDR = ("variant", "F1", "P", "R", "cov", "holeS", "holeM", "holeL", "endgap", "missed", "dangle",
       "dnear", "sealed", "rooms", "nseg", "len", "door_cov", "ondoor", "false_px", "time",
       "lowp", "nlowseg", "skdev", "dev3", "dev6", "nbr", "brF", "br_px", "br_gt", "br_door", "br_false")


def fmt_row(name, d):
    cells = [f"{name:22s}"]
    for k in HDR[1:]:
        v = d[k]
        cells.append(f"{v:.3f}" if k in ("F1", "P", "R", "cov", "door_cov", "time", "lowp", "skdev", "dev3", "dev6", "br_gt", "br_door", "br_false") else f"{int(round(v))}")
    return " ".join(f"{c:>7s}" if i else c for i, c in enumerate(cells))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache_dir", default="")
    ap.add_argument("--build_cache", action="store_true")
    ap.add_argument("--ckpt", default="pipeline/models/wall_student_convnext_tiny.onnx")
    ap.add_argument("--encoder", default="tu-convnext_tiny")
    ap.add_argument("--scales", default="1024")
    ap.add_argument("--fa_list", default="corpus/fa_test_inscope.txt")
    ap.add_argument("--wall_thr", type=float, default=0.5)
    ap.add_argument("--variants", default="default:")
    ap.add_argument("--per_map", action="store_true")
    ap.add_argument("--overlay_dir", default="")
    ap.add_argument("--json", default="", help="dump all per-map results (incl. hole list)")
    ap.add_argument("--procs", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", "4")))
    ap.add_argument("--image", default="", help="GT-free mode: one image, prints dangle/lowp/skdev")
    ap.add_argument("--image_cache", default="", help="npz to cache the image's probability maps")
    ap.add_argument("--out", default="", help="--image: overlay path (yellow=segments, red=low-"
                    "probability segments, magenta dots=dangling ends)")
    ap.add_argument("--show_prob", action="store_true", help="--image: paint wall probability in green")
    a = ap.parse_args()
    if a.image:
        image_mode(a)
        return
    if a.build_cache:
        build_cache(a)
        return
    slugs = [ln.strip() for ln in open(a.fa_list) if ln.strip()]
    slugs = [s for s in slugs if os.path.exists(os.path.join(a.cache_dir, s + ".npz"))]
    variants = parse_variants(a.variants)
    if a.overlay_dir:
        os.makedirs(a.overlay_dir, exist_ok=True)
    jobs = [(a.cache_dir, s, name, kw, a.wall_thr, a.overlay_dir) for s in slugs for name, kw in variants]
    with Pool(a.procs) as pool:
        res = pool.map(_job, jobs, chunksize=max(1, len(variants)))
    by = defaultdict(list)
    for r in res:
        by[r["variant"]].append(r)
    print(f"n_maps={len(slugs)} wall_thr={a.wall_thr}")
    print(" ".join(f"{c:>7s}" if i else f"{c:22s}" for i, c in enumerate(HDR)))
    for name, _ in variants:
        print(fmt_row(name, summarize(by[name])), flush=True)
    for name, _ in variants:
        causes = defaultdict(lambda: defaultdict(int))
        for r in by[name]:
            for h in r["holes"]:
                causes[h["bucket"]][h["cause"]] += 1
        print(f"hole causes [{name}]: " + "  ".join(
            f"{b}: " + ",".join(f"{c}={causes[b][c]}" for c in ("vectorizer", "offcentre", "weakprob", "nopred", "door"))
            for b in "SML"))
    if a.per_map:
        for name, _ in variants:
            print(f"\n--- per map [{name}]")
            for r in by[name]:
                print(f"{r['slug'][:34]:34s} F1={r['F1']:.3f} P={r['P']:.3f} R={r['R']:.3f} cov={r['cov']:.3f} "
                      f"holes={r['holeS']}/{r['holeM']}/{r['holeL']} end={r['endgap']} miss={r['missed']} "
                      f"dangle={r['dangle']}({r['dnear']}) sealed={r['sealed']}/{r['rooms']} nseg={r['nseg']} "
                      f"doorcov={r['door_cov_px']}/{r['door_px']}")
    if a.json:
        json.dump(res, open(a.json, "w"))


if __name__ == "__main__":
    main()
