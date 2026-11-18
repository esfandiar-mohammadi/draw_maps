#!/usr/bin/env python
"""Detect the square grid PRINTED in a battle-map image (numpy + opencv only).

    detect_grid(img_bgr) -> {
        "found": bool,            # only True when the detector is confident
        "size": float | None,     # px per cell, sub-pixel (NOT snapped to int)
        "offset_x": float | None, # position of a vertical grid line, in [0,size)
        "offset_y": float | None, # position of a horizontal grid line, in [0,size)
        "size_x": float | None,   # per-axis period estimates
        "size_y": float | None,
        "coverage": float | None, # share of the map on which the lines are visible
        "confidence": float,      # 0..1
        "reason": str,            # "" when found, else why not
        "candidate": {...} | None # best guess when found is False (do NOT apply)
    }

Coordinates are ORIGINAL image pixels in the continuous convention used by
Foundry / UVTT: pixel i covers [i, i+1), so a 2-px line painted on pixel
columns 127 and 128 sits at x = 128.0. Grid lines are at offset + k*size.

Method
  1. Work image: gray, long side reduced to <= WORK_LONG (area resampling).
  2. Per axis, average the image in thin bands along the line direction
     (keeps dotted / faint lines, kills texture), then apply a thin-LINE
     filter across it: min(centre-left, centre-right). A step edge (wall
     boundary) gives 0, a 1-4 px line gives its contrast. Normalise by the
     band's own local contrast and clip, so one loud object cannot outvote a
     faint line that is present in every band. Mean over bands -> 1-D profile.
  3. Fold the profile modulo every candidate period (sub-pixel steps) and take
     the peak of the folded profile in noise units. This score is highest at
     the fundamental: a multiple k*P has the same peak height but sqrt(k) more
     noise, P/2 has half the peak height. x and y are scored on the same
     candidates and summed (the grid is square), both line polarities tried.
  4. Per axis, locate every individual line near the predicted teeth and fit
     position = offset + k*period by robust least squares -> sub-pixel period
     and phase, plus how many of the expected lines really exist.
  5. Verdict: found only if both axes are strong, most expected lines exist,
     the evidence is spread over the image, x/y periods agree, and no
     half/double period explains the data about as well. A grid that is
     visible on only part of the map (printed on the floors, not on the rock)
     is accepted only when all other checks pass with a wide margin.
"""
import argparse
import json
import math
import os

import cv2
import numpy as np

WORK_LONG = 2048      # long side of the work image
BAND = 8              # band height (work px) for the along-line averaging
ZCLIP = 3.0           # clip of the per-band normalised line response
PMIN = 8.0            # smallest period searched (work px)
MIN_CELLS = 3.5       # the shorter image side must hold at least this many cells

# verdict thresholds (tuned with tools/bench_grid_detect.py)
T_Z = 8.0             # min fold z-score per axis
T_TEETH = 0.60        # min fraction of expected lines that are really there
T_COVER = 0.70        # min fraction of map blocks in which the lines are visible
T_AGREE = 0.004       # max relative disagreement of x and y period
T_HARM_LO = 0.93      # p/2 or p/3 scoring above this fraction of p is ambiguous (theory: 0.71 / 1.41)
T_HARM_HI = 0.85      # 2p or 3p scoring above this fraction of p is ambiguous (theory: 0.71)
T_ALT = 0.60          # even/odd line strength ratio below this is ambiguous
T_RIVAL = 0.80        # an unrelated period scoring above this fraction is ambiguous
T_SIDE = 0.60         # second peak of the folded profile above this fraction is ambiguous
T_CONF = 0.82         # min combined confidence (all checks passed, but several only just)
# "partial" grids (printed on the floors only, not on rock/void): coverage down to
# T_COVER_PART is accepted, but only when every other check passes with a wide margin
T_COVER_PART = 0.35
P_Z, P_TEETH, P_ALT, P_SIDE, P_RIVAL, P_HARM, P_LINES = 20.0, 0.72, 0.85, 0.30, 0.60, 0.80, 8


def _line_response(gray, axis):
    """Band-averaged, normalised thin-line response.

    axis=0: vertical lines -> returns (n_bands, W). axis=1: horizontal lines ->
    returns (n_bands, H) (the image is transposed so lines are always columns).
    """
    g = gray if axis == 0 else gray.T
    h, w = g.shape
    nb = max(8, h // BAND)
    b = cv2.resize(np.ascontiguousarray(g), (w, nb), interpolation=cv2.INTER_AREA)
    c = cv2.blur(b, (3, 1), borderType=cv2.BORDER_REFLECT)
    # side references: mean of the pixels 3..6 away on each side
    k = np.zeros((1, 13), np.float32)
    kl, kr = k.copy(), k.copy()
    kl[0, 0:4] = 0.25                     # x-6 .. x-3
    kr[0, 9:13] = 0.25                    # x+3 .. x+6
    left = cv2.filter2D(b, -1, kl, borderType=cv2.BORDER_REFLECT)
    right = cv2.filter2D(b, -1, kr, borderType=cv2.BORDER_REFLECT)
    dl, dr = c - left, c - right
    r = np.where((dl > 0) & (dr > 0), np.minimum(dl, dr), 0.0) \
        - np.where((dl < 0) & (dr < 0), np.minimum(-dl, -dr), 0.0)
    # local contrast scale per band (robust), floored so flat areas don't explode
    d = b[:, 4:] - b[:, :-4]
    sig = 1.4826 * np.median(np.abs(d - np.median(d, axis=1, keepdims=True)), axis=1)
    sig = np.maximum(sig, 1.0)[:, None]
    return np.clip(r / sig, -ZCLIP, ZCLIP).astype(np.float32)


def _robust_sigma(s):
    return float(1.4826 * np.median(np.abs(s - np.median(s))) + 1e-6)


def _candidates(pmin, pmax, length):
    """Periods spaced so that neighbouring candidates drift <= 1 px over `length`."""
    n = int(math.log(pmax / pmin) / math.log1p(1.0 / length)) + 1
    return pmin * (1.0 + 1.0 / length) ** np.arange(n)


def _fold_scores(s, cands, chunk=2_000_000):
    """z-score of the folded-profile peak for both polarities, per candidate period.

    Fold = mean of the profile over all x with the same (x mod p), 1-px bins.
    """
    n = len(s)
    cands = np.asarray(cands, np.float64)
    x = np.arange(n, dtype=np.float64)
    sig = _robust_sigma(s)
    zp = np.empty(len(cands), np.float32)
    zn = np.empty(len(cands), np.float32)
    step = max(1, chunk // n)
    for a in range(0, len(cands), step):
        p = cands[a:a + step]
        nb = np.floor(p).astype(np.int64)      # bins >= 1 px, so none runs empty
        off = np.concatenate([[0], np.cumsum(nb)])
        idx = (np.mod(x[None, :], p[:, None]) * (nb / p)[:, None]).astype(np.int64)
        np.minimum(idx, (nb - 1)[:, None], out=idx)
        idx += off[:-1, None]
        idx = idx.ravel()
        cnt = np.bincount(idx, minlength=off[-1])
        f = np.bincount(idx, weights=np.tile(s, len(p)), minlength=off[-1]) / np.maximum(cnt, 1)
        mx = np.maximum.reduceat(f, off[:-1])
        mn = np.minimum.reduceat(f, off[:-1])
        m = np.add.reduceat(f, off[:-1]) / nb
        noise = sig / np.sqrt(n / nb)
        zp[a:a + step] = (mx - m) / noise
        zn[a:a + step] = (m - mn) / noise
    return zp, zn


def _fine_z(s, p, pol, width=0.012, n=41):
    """Best fold z-score and period in a narrow window around p."""
    fine = np.linspace(p * (1 - width), p * (1 + width), n)
    z = _fold_scores(s, fine)[0 if pol > 0 else 1]
    i = int(np.argmax(z))
    return float(z[i]), float(fine[i])


def _fold_phase(s, p, pol):
    """Phase (work px, index coords) of the folded-profile peak, 1/4-px bins."""
    n = len(s)
    nb = int(math.ceil(p * 4))
    x = np.arange(n, dtype=np.float64)
    idx = np.minimum(((x % p) * (nb / p)).astype(np.int64), nb - 1)
    f = np.bincount(idx, weights=pol * s, minlength=nb) / np.maximum(np.bincount(idx, minlength=nb), 1)
    f = np.convolve(np.r_[f[-4:], f, f[:4]], np.ones(5) / 5, mode="same")[4:-4]
    return (int(np.argmax(f)) + 0.5) * p / nb


def _fit_lines(s, p0, phi0, pol):
    """Locate the individual lines near the teeth phi0 + k*p0 and fit a line.

    Returns dict(period, phase, n_teeth, n_hit, frac, resid, perr) or None.
    """
    n = len(s)
    sp = pol * s
    sig = _robust_sigma(s)
    p, phi = p0, phi0
    res = None
    for it in range(3):
        k0 = int(math.ceil((2 - phi) / p))
        k1 = int(math.floor((n - 3 - phi) / p))
        ks = np.arange(k0, k1 + 1)
        if len(ks) < 3:
            return None
        win = max(2, int(round(min(0.2 * p, 4 if it else 6))))
        pos, kk, amp = [], [], []
        for k in ks:
            c = phi + k * p
            a, b = max(1, int(round(c)) - win), min(n - 2, int(round(c)) + win)
            if b <= a:
                continue
            j = a + int(np.argmax(sp[a:b + 1]))
            v = sp[j]
            if v < 2.0 * sig:
                continue
            lo, hi = max(0, j - 3), min(n, j + 4)
            w = np.maximum(sp[lo:hi] - 0.4 * v, 0)
            pos.append(float((w * np.arange(lo, hi)).sum() / w.sum()))
            kk.append(k)
            amp.append(v)
        if len(pos) < 3:
            return None
        pos, kk = np.array(pos), np.array(kk, np.float64)
        keep = np.ones(len(pos), bool)
        for _ in range(3):
            A = np.stack([kk[keep], np.ones(keep.sum())], 1)
            (pf, ph), *_ = np.linalg.lstsq(A, pos[keep], rcond=None)
            r = pos - (pf * kk + ph)
            new = np.abs(r) <= max(1.0, 2.5 * np.std(r[keep]))
            if new.sum() < 3 or (new == keep).all():
                break
            keep = new
        nh = int(keep.sum())
        resid = float(np.sqrt(np.mean(r[keep] ** 2)))
        span = float(np.sqrt(((kk[keep] - kk[keep].mean()) ** 2).sum()))
        res = {"period": float(pf), "phase": float(ph % pf), "n_teeth": int(len(ks)),
               "n_hit": nh, "frac": nh / len(ks), "resid": resid,
               "perr": max(resid, 0.15) / max(span, 1e-6) / pf,
               "amp": float(np.median(np.array(amp)[keep]) / sig)}
        p, phi = float(pf), float(ph)
    return res


def _teeth_present(s, p, phi, pol):
    """Fraction of the expected lines that exist (noise-corrected).

    A line counts when its strength exceeds 35 % of a typical strong line; the
    rate at which off-grid positions pass the same test is subtracted.
    """
    n = len(s)
    sp = pol * s

    def at(shift):
        c = phi + shift * p + p * np.arange(int(math.ceil((1 - phi - shift * p) / p)),
                                            int(math.floor((n - 2 - phi - shift * p) / p)) + 1)
        c = np.round(c).astype(int)
        c = c[(c >= 1) & (c <= n - 2)]
        return np.maximum(np.maximum(sp[c - 1], sp[c]), sp[c + 1])
    v = at(0.0)
    if len(v) < 3:
        return 0.0
    ref = np.percentile(v, 75)
    if ref <= 0:
        return 0.0
    null = np.concatenate([at(0.25), at(0.375), at(0.625), at(0.75)])
    fp = float((null > 0.35 * ref).mean()) if len(null) else 0.0
    return float(max(0.0, ((v > 0.35 * ref).mean() - fp) / max(1e-6, 1 - fp)))


def _side_peak(s, p, phi, pol):
    """Second-highest peak of the profile folded at p, relative to the grid peak.

    ~0 for a clean grid. Near 1 when other equally periodic lines sit at another
    phase (floor boards, tiles): then the phase - or the period - is a guess.
    """
    n = len(s)
    nb = int(math.floor(p))
    x = np.arange(n, dtype=np.float64)
    idx = np.minimum((np.mod(x - phi + p / 2, p) * (nb / p)).astype(np.int64), nb - 1)
    f = np.bincount(idx, weights=pol * s, minlength=nb) / np.maximum(np.bincount(idx, minlength=nb), 1)
    f = f - np.median(f)
    c = nb // 2                                  # the grid line sits in the middle bin
    w = max(3, int(round(0.1 * nb)))
    main = f[c - 2:c + 3].max()
    rest = np.concatenate([f[:c - w], f[c + w + 1:]])
    if main <= 0 or len(rest) == 0:
        return 1.0
    return float(max(rest.max(), 0.0) / main)


def _alternation(s, p, phi, pol):
    """min/max ratio of the mean line strength on even vs odd teeth (1 = uniform)."""
    n = len(s)
    ks = np.arange(int(math.ceil((1 - phi) / p)), int(math.floor((n - 2 - phi) / p)) + 1)
    if len(ks) < 4:
        return 1.0
    c = np.round(phi + ks * p).astype(int)
    v = np.maximum(np.maximum(pol * s[c - 1], pol * s[c]), pol * s[c + 1])
    e, o = v[ks % 2 == 0].mean(), v[ks % 2 == 1].mean()
    hi = max(e, o)
    return float(max(min(e, o), 0.0) / hi) if hi > 0 else 1.0


def _coverage(gray, zx, zy, p_x, phi_x, p_y, phi_y, pol):
    """Fraction of grid EDGES (cell sides) on which the line is really visible.

    A painted grid crosses everything; floor-tile seams or wall rows exist only
    in parts of the map. Cell sides between two perfectly flat cells (void
    around the map) are not counted. Returns (coverage, n_edges_counted).
    """
    H, W = gray.shape
    xs = phi_x + p_x * np.arange(int(math.ceil((2 - phi_x) / p_x)), int(math.floor((W - 3 - phi_x) / p_x)) + 1)
    ys = phi_y + p_y * np.arange(int(math.ceil((2 - phi_y) / p_y)), int(math.floor((H - 3 - phi_y) / p_y)) + 1)
    if len(xs) < 2 or len(ys) < 2:
        return 0.0, 0
    # flat-cell map from integral images (cells shrunk by 20 % to stay off the lines)
    s1, s2 = cv2.integral2(gray.astype(np.float64))
    ex = np.concatenate([[xs[0] - p_x], xs, [xs[-1] + p_x]])
    ey = np.concatenate([[ys[0] - p_y], ys, [ys[-1] + p_y]])

    def box(e, p, lim):
        lo = np.clip(np.round(e[:-1] + 0.2 * p).astype(int), 0, lim)
        hi = np.clip(np.round(e[1:] - 0.2 * p).astype(int), 0, lim)
        return lo, np.maximum(hi, lo)
    x0, x1 = box(ex, p_x, W)
    y0, y1 = box(ey, p_y, H)
    area = np.maximum((y1 - y0)[:, None] * (x1 - x0)[None, :], 1)

    def rect(ii):
        return ii[y1][:, x1] - ii[y0][:, x1] - ii[y1][:, x0] + ii[y0][:, x0]
    m = rect(s1) / area
    var = np.maximum(rect(s2) / area - m * m, 0)
    # cells where a line of this polarity cannot show: perfectly flat (void around
    # the map), or already black for a dark grid / white for a light grid
    flat = (var < 2.0 ** 2) | ((y1 - y0)[:, None] * (x1 - x0)[None, :] < 4)   # (len(ys)+1, len(xs)+1)
    flat |= (m < 24) if pol < 0 else (m > 231)

    def edges(z, lines, cross_edges, length):
        """Per-edge line energy: rows = cross cells, cols = lines."""
        nb, n = z.shape
        c = np.round(lines).astype(int)
        col = pol * (z[:, c - 1] + z[:, c] + z[:, c + 1])                 # (bands, lines)
        cm = np.round(lines + 0.5 * (lines[1] - lines[0])).astype(int)
        cm = cm[cm + 1 < n]
        null = pol * (z[:, cm - 1] + z[:, cm] + z[:, cm + 1])            # mid-cell columns
        bb = np.clip(np.round(cross_edges * nb / length).astype(int), 0, nb)

        def agg(a):
            cs = np.concatenate([np.zeros((1, a.shape[1])), np.cumsum(a, axis=0)])
            cnt = np.maximum(bb[1:] - bb[:-1], 1)[:, None]
            return (cs[bb[1:]] - cs[bb[:-1]]) / cnt
        return agg(col), agg(null)
    rx, nx = edges(zx, xs, ey, H)       # (cells_y, lines_x), null (cells_y, <=lines_x)
    ry, ny = edges(zy, ys, ex, W)       # (cells_x, lines_y)
    ry, ny = ry.T, ny.T                 # -> (lines_y, cells_x)
    use_x = ~(flat[:, :-1] & flat[:, 1:])          # (cells_y, lines_x)
    use_y = ~(flat[:-1, :] & flat[1:, :])          # (lines_y, cells_x)
    ncy, ncx = flat.shape
    # blocks of bs x bs cells: enough averaging for faint lines, still local
    bs = int(min(4, max(1, round(min(ncx, ncy) / 8))))
    vals = []
    for by in range(0, ncy, bs):
        for bx in range(0, ncx, bs):
            ux = use_x[by:by + bs, bx:bx + bs]
            uy = use_y[by:by + bs, bx:bx + bs]
            n_use, n_all = ux.sum() + uy.sum(), ux.size + uy.size
            if n_all == 0 or n_use < 0.3 * n_all or n_use < 2:
                continue
            on = (rx[by:by + bs, bx:bx + bs][ux].sum() + ry[by:by + bs, bx:bx + bs][uy].sum()) / n_use
            nxb, nyb = nx[by:by + bs, bx:bx + bs], ny[by:by + bs, bx:bx + bs]
            off = (nxb.sum() + nyb.sum()) / max(1, nxb.size + nyb.size)
            vals.append(on - off)
    if len(vals) < 6:
        return 0.0, len(vals)
    vals = np.array(vals)
    ref = np.percentile(vals, 75)
    if ref <= 0:
        return 0.0, len(vals)
    return float((vals > 0.35 * ref).mean()), len(vals)


def _not_found(reason, conf=0.0, cand=None):
    return {"found": False, "size": None, "offset_x": None, "offset_y": None,
            "size_x": None, "size_y": None, "coverage": None, "confidence": round(float(conf), 3),
            "reason": reason, "candidate": cand}


def detect_grid(img_bgr, debug=False):
    """See module docstring. Returns found=False (with a reason) when unsure."""
    if img_bgr is None or img_bgr.ndim < 2:
        return _not_found("no image")
    gray = img_bgr if img_bgr.ndim == 2 else cv2.cvtColor(img_bgr[:, :, :3], cv2.COLOR_BGR2GRAY)
    H0, W0 = gray.shape
    if min(H0, W0) < 64:
        return _not_found("image too small")
    f = min(1.0, WORK_LONG / max(H0, W0))
    if f < 1.0:
        gray = cv2.resize(gray, (max(1, round(W0 * f)), max(1, round(H0 * f))),
                          interpolation=cv2.INTER_AREA)
    gray = gray.astype(np.float32)
    H, W = gray.shape
    fx, fy = W / W0, H / H0           # exact per-axis scale after rounding

    zx = _line_response(gray, 0)      # (bands, W)
    zy = _line_response(gray, 1)      # (bands, H)
    ker = np.array([0.25, 0.5, 0.25])
    sx = np.convolve(zx.mean(axis=0), ker, mode="same")
    sy = np.convolve(zy.mean(axis=0), ker, mode="same")

    pmax = min(W, H) / MIN_CELLS
    if pmax <= PMIN * 1.5:
        return _not_found("image too small")
    cands = _candidates(PMIN, pmax, max(W, H))
    zxp, zxn = _fold_scores(sx, cands)
    zyp, zyn = _fold_scores(sy, cands)
    jp, jn = zxp + zyp, zxn + zyn
    pol = 1.0 if jp.max() >= jn.max() else -1.0
    J = jp if pol > 0 else jn
    i0 = int(np.argmax(J))
    p = float(cands[i0])
    feats = {"pol": pol, "j0": float(J[i0])}

    def fine(q):
        a, b = _fine_z(sx, q, pol), _fine_z(sy, q, pol)
        return a[0] + b[0], a, b

    # resolve the fundamental: go to p/2, p/3 while that explains the data better
    jf, fxz, fyz = fine(p)
    if not (np.isfinite(jf) and jf > 0):
        return _not_found("no periodic lines in the image")
    harm_lo = 0.0
    for _ in range(3):
        harm_lo, best = 0.0, None
        for q in (2, 3):
            if p / q < PMIN:
                continue
            r = fine(p / q)
            harm_lo = max(harm_lo, r[0] / jf)
            if r[0] > jf and (best is None or r[0] > best[1][0]):
                best = (p / q, r)
        if best is None:
            break
        p, (jf, fxz, fyz) = best
    harm_hi = 0.0
    for q in (2, 3):
        if p * q <= min(W, H) / 2.5:
            harm_hi = max(harm_hi, fine(p * q)[0] / jf)
    # unrelated rival periods (coarse scan)
    ratio = cands / p
    rel = np.zeros(len(cands), bool)
    for q in (1, 2, 3, 4, 5, 6, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 6, 1.5, 2 / 3, 2.5, 0.4):
        rel |= np.abs(ratio / q - 1) < 0.03
    if (~rel).any():
        k = int(np.argmax(np.where(rel, -1, J)))
        feats["rival"], feats["rival_p"] = float(J[k] / jf), float(cands[k] / fx)
    else:
        feats["rival"], feats["rival_p"] = 0.0, 0.0
    feats.update({"harm_lo": harm_lo, "harm_hi": harm_hi})

    fits = []
    for s, (zf, pa) in ((sx, fxz), (sy, fyz)):
        fit = _fit_lines(s, pa, _fold_phase(s, pa, pol), pol)
        if fit is not None:
            fit["z"] = zf
            fit["alt"] = _alternation(s, fit["period"], fit["phase"], pol)
            fit["frac"] = _teeth_present(s, fit["period"], fit["phase"], pol)
            fit["side"] = _side_peak(s, fit["period"], fit["phase"], pol)
        fits.append(fit)

    def finish(res):
        if debug:
            res["debug"] = feats
        return res

    if fits[0] is None or fits[1] is None:
        return finish(_not_found("no consistent grid lines on %s axis"
                                 % ("x" if fits[0] is None else "y")))
    ax, ay = fits
    cover, n_edges = _coverage(gray, zx, zy, ax["period"], ax["phase"], ay["period"], ay["phase"], pol)
    px, py = ax["period"] / fx, ay["period"] / fy
    wx, wy = 1 / ax["perr"] ** 2, 1 / ay["perr"] ** 2
    size = (px * wx + py * wy) / (wx + wy)
    # work-px index coords -> original continuous coords (pixel i = [i, i+1))
    offx = ((ax["phase"] + 0.5) / fx) % size
    offy = ((ay["phase"] + 0.5) / fy) % size
    agree = abs(px - py) / size
    feats.update({"zx": ax["z"], "zy": ay["z"], "teeth_x": ax["frac"], "teeth_y": ay["frac"],
                  "n_x": ax["n_hit"], "n_y": ay["n_hit"], "agree": float(agree),
                  "resid_x": ax["resid"], "resid_y": ay["resid"], "amp_x": ax["amp"],
                  "amp_y": ay["amp"], "alt_x": ax["alt"], "alt_y": ay["alt"],
                  "side_x": ax["side"], "side_y": ay["side"],
                  "cover": cover, "n_edges": n_edges})

    def soft(v, lo, hi):
        return float(min(1.0, max(0.0, (v - lo) / (hi - lo))))
    zmin = min(ax["z"], ay["z"])
    teeth = min(ax["frac"], ay["frac"])
    alt = min(ax["alt"], ay["alt"])
    side = max(ax["side"], ay["side"])
    partial = (T_COVER_PART <= cover < T_COVER and zmin >= P_Z and teeth >= P_TEETH
               and alt >= P_ALT and side <= P_SIDE and feats["rival"] <= P_RIVAL
               and harm_lo <= P_HARM and harm_hi <= P_HARM
               and min(ax["n_hit"], ay["n_hit"]) >= P_LINES)
    feats["partial"] = bool(partial)
    parts = [soft(zmin, T_Z * 0.5, T_Z * 2.5), soft(teeth, T_TEETH - 0.2, 1.0),
             1.0 if partial else soft(cover, T_COVER - 0.2, 1.0),
             soft(-agree, -2 * T_AGREE, -T_AGREE / 4),
             soft(-harm_lo, -(T_HARM_LO + 0.07), -(T_HARM_LO - 0.13)),
             soft(-harm_hi, -(T_HARM_HI + 0.1), -(T_HARM_HI - 0.1)), soft(alt, T_ALT - 0.2, T_ALT + 0.2),
             soft(-feats["rival"], -(T_RIVAL + 0.1), -(T_RIVAL - 0.3)),
             soft(-side, -(T_SIDE + 0.1), -(T_SIDE - 0.2))]
    conf = float(np.prod(parts)) ** (1 / len(parts))
    if partial:
        conf *= 0.9                   # never as sure as a grid that covers the whole map

    reason = ""
    if zmin < T_Z:
        reason = "grid lines too weak (z=%.1f)" % zmin
    elif min(ax["n_hit"], ay["n_hit"]) < 4:
        reason = "too few grid lines"
    elif teeth < T_TEETH:
        reason = "only %.0f%% of the expected grid lines exist" % (100 * teeth)
    elif agree > T_AGREE:
        reason = "x and y periods disagree (%.2f vs %.2f)" % (px, py)
    elif harm_lo > T_HARM_LO:
        reason = "ambiguous: half the period fits about as well"
    elif harm_hi > T_HARM_HI:
        reason = "ambiguous: double the period fits about as well"
    elif alt < T_ALT:
        reason = "ambiguous: every second line is much weaker"
    elif cover < T_COVER and not partial:
        reason = "periodic lines cover only %.0f%% of the map (floor tiles?)" % (100 * cover)
    elif side > T_SIDE:
        reason = "ambiguous: other periodic lines (boards/tiles?) at a different position"
    elif feats["rival"] > T_RIVAL:
        reason = "ambiguous: another period (%.1f px) fits about as well" % feats["rival_p"]

    if not reason and conf < T_CONF:
        reason = "evidence is borderline on several checks"
    vals = {"size": round(float(size), 3), "offset_x": round(float(offx), 2),
            "offset_y": round(float(offy), 2), "size_x": round(float(px), 3),
            "size_y": round(float(py), 3), "coverage": round(float(cover), 2)}
    if reason:
        return finish(_not_found(reason, min(conf, T_CONF - 0.01), vals))
    return finish({"found": True, **vals, "confidence": round(conf, 3),
                   "reason": "", "candidate": None})


def run(inp, out=None, pmin=20, pmax=400):
    """Legacy entry point (grid_walls / sam_walls / auto / seg_to_walls).

    Always returns an integer "grid" + offsets (best guess even when the
    detector is not confident); "found"/"conf" say whether to trust it.
    """
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    H, W = img.shape[:2]
    g = detect_grid(img)
    v = g if g["found"] else (g["candidate"] or {"size": 70.0, "offset_x": 0.0, "offset_y": 0.0})
    res = {"input": os.path.basename(inp), "size": [W, H],
           "grid": int(round(v["size"])), "grid_f": v["size"],
           "offset_x": round(float(v["offset_x"]), 1), "offset_y": round(float(v["offset_y"]), 1),
           "conf": g["confidence"], "conf_x": g["confidence"], "conf_y": g["confidence"],
           "found": g["found"], "reason": g["reason"]}
    if out:
        os.makedirs(out, exist_ok=True)
        cv2.imwrite(os.path.join(out, "grid_overlay.png"), draw_overlay(img, v))
        with open(os.path.join(out, "grid.json"), "w") as fh:
            json.dump(res, fh, indent=1)
    print(json.dumps(res))
    return res


def draw_overlay(img, g, color=(0, 255, 0)):
    ov = img.copy()
    H, W = ov.shape[:2]
    for x in np.arange(g["offset_x"], W, g["size"]):
        cv2.line(ov, (int(round(x)), 0), (int(round(x)), H), color, 1)
    for y in np.arange(g["offset_y"], H, g["size"]):
        cv2.line(ov, (0, int(round(y))), (W, int(round(y))), color, 1)
    return ov


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    if a.out:
        run(a.input, a.out)
    else:
        print(json.dumps(detect_grid(cv2.imread(a.input, cv2.IMREAD_COLOR), debug=True)))
