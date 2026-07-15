#!/usr/bin/env python
"""Estimate the pixel-per-cell grid period and phase of a battlemap.

Method: vertical grid lines produce strong vertical edges -> Sobel-x, abs,
sum over rows -> 1D signal over x with peaks at grid lines. Autocorrelation of
that signal gives the period; a comb-filter score over candidate integer
periods refines it and snaps to a round number. Phase found by aligning a comb.
Reports period_x, period_y, a confidence per axis, and the best phase.
"""
import os, sys, json, argparse
import cv2, numpy as np


def axis_signal(gray, axis):
    # axis=0 -> vertical lines (Sobel x, sum over rows) ; axis=1 -> horizontal
    if axis == 0:
        g = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)).sum(axis=0)
    else:
        g = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)).sum(axis=1)
    g = g - cv2.GaussianBlur(g.reshape(-1, 1), (1, 0), 0, sigmaY=15).ravel()  # detrend
    return g


def comb_score(sig, period, n_off=None):
    """Best comb-filter score over phase for a given (float) period."""
    L = len(sig)
    s = (sig - sig.mean())
    s = s / (s.std() + 1e-9)
    if n_off is None:
        n_off = max(2, int(round(period)))
    best = -1e9; best_off = 0
    for off in np.linspace(0, period, num=min(n_off, 40), endpoint=False):
        idx = np.round(np.arange(off, L, period)).astype(int)
        idx = idx[idx < L]
        if len(idx) < 3:
            continue
        val = s[idx].mean()
        if val > best:
            best = val; best_off = off
    return best, best_off


def estimate_period(sig, pmin=20, pmax=400):
    pmax = min(pmax, len(sig) // 3)
    cands = range(pmin, pmax + 1)
    scored = {p: comb_score(sig, p)[0] for p in cands}
    best_p = max(scored, key=scored.get)
    best_score = scored[best_p]
    # Reduce to the FUNDAMENTAL: if a divisor of best_p scores nearly as well,
    # the real period is the divisor (best_p was a harmonic, e.g. 210 = 3*70).
    for d in (5, 4, 3, 2):
        fp = best_p / d
        if fp < pmin:
            continue
        fpi = int(round(fp))
        if fpi in scored and scored[fpi] >= 0.55 * best_score:
            best_p = fpi
            best_score = scored[fpi]
            break
    _, off = comb_score(sig, best_p, n_off=best_p)
    med = np.median(list(scored.values())) + 1e-9
    conf = best_score / med
    return best_p, off, round(float(best_score), 3), round(float(conf), 2)


def run(inp, out=None, pmin=20, pmax=400):
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = gray.shape
    sx = axis_signal(gray, 0)
    sy = axis_signal(gray, 1)
    px, ox, scx, cfx = estimate_period(sx, pmin, pmax)
    py, oy, scy, cfy = estimate_period(sy, pmin, pmax)
    # Grids are square: reconcile the two axes to one period (prefer the more
    # confident axis; if the other is ~a multiple, keep the fundamental).
    if abs(px - py) > 2:
        if cfx >= cfy:
            base = px
        else:
            base = py
        # re-snap the weaker axis's phase to `base`
        ox = comb_score(sx, base, n_off=base)[1]
        oy = comb_score(sy, base, n_off=base)[1]
        px = py = base
    grid = int(round((px + py) / 2))
    conf = round(min(cfx, cfy), 2)
    res = {"input": os.path.basename(inp), "size": [W, H],
           "grid": grid, "offset_x": round(float(ox), 1), "offset_y": round(float(oy), 1),
           "conf": conf, "conf_x": cfx, "conf_y": cfy}
    if out:
        os.makedirs(out, exist_ok=True)
        ov = img.copy()
        for x in np.arange(ox, W, grid):
            cv2.line(ov, (int(x), 0), (int(x), H), (0, 255, 0), 1)
        for y in np.arange(oy, H, grid):
            cv2.line(ov, (0, int(y)), (W, int(y)), (0, 255, 0), 1)
        cv2.imwrite(os.path.join(out, "grid_overlay.png"), ov)
        json.dump(res, open(os.path.join(out, "grid.json"), "w"), indent=1)
    print(json.dumps(res))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--pmin", type=int, default=20)
    ap.add_argument("--pmax", type=int, default=400)
    a = ap.parse_args()
    run(a.input, a.out, a.pmin, a.pmax)
