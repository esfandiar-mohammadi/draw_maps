#!/usr/bin/env python
"""Benchmark pipeline/grid_detect.py against UVTT ground truth + a synthetic stress set.

Sets
  real-vtt    vendor/vtt-maps + corpus/real_uvtt, untouched (many have a printed grid)
  real-fa     corpus/fa, untouched (almost all have NO printed grid -> the right
              answer is "not found" or the right period; anything else is wrong)
  syn-xform   real-vtt maps, random crop (phase != 0) + non-integer resize
  syn-faint   corpus/fa maps, random crop + resize, then a faint semi-transparent
              grid (white/black, alpha 0.1-0.4, 1-2 px) painted on the true layout,
              half of them JPEG-compressed, half resized AFTER painting
  syn-misaligned  corpus/fa maps with a grid of RANDOM period and phase painted on
              (alpha 0.15-0.5, 1-3 px): the detector must report the painted
              grid, not the map's own tile/wall rhythm

  syn-partial corpus/fa maps, crop + resize, then a grid painted ONLY inside a
              random smooth blob covering 35-65 % of the image (grids printed on
              the floors but not on the surrounding rock), alpha 0.2-0.5

Ground truth: period = resolution.pixels_per_grid, a grid line at
-map_origin*ppg (i.e. the image's top-left corner for nearly all files).

Verdict per map (only when the detector says found=True):
  ok        period within 1 % and every grid line within 15 % of a cell of GT
  harmonic  period is GT times/divided by 2,3,4 (or 1.5)      -> confidently wrong
  period    any other wrong period                             -> confidently wrong
  phase     period ok but lines are shifted > 15 % of a cell   -> confidently wrong

Run (compute goes through Slurm on this box):
  sbatch --cpus-per-task=8 --wrap \
    ".venv/bin/python tools/bench_grid_detect.py --workers 8 --out /tmp/grid_bench.jsonl"
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
from multiprocessing import Pool

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import grid_detect  # noqa: E402

cv2.setNumThreads(1)
PHASE_TOL = 0.15


def find_uvtt(*roots):
    out = []
    for r in roots:
        for dp, _, fn in os.walk(os.path.join(ROOT, r)):
            if "_dupes" in dp:
                continue
            out += [os.path.join(dp, f) for f in fn if f.lower().endswith((".dd2vtt", ".uvtt"))]
    return sorted(out)


def load(path):
    with open(path) as fh:
        d = json.load(fh)
    r = d["resolution"]
    ppg = float(r["pixels_per_grid"])
    o = r.get("map_origin", {}) or {}
    img = cv2.imdecode(np.frombuffer(base64.b64decode(d["image"]), np.uint8), cv2.IMREAD_COLOR)
    return img, ppg, (-float(o.get("x", 0)) * ppg) % ppg, (-float(o.get("y", 0)) * ppg) % ppg


def rng_for(path, variant):
    h = hashlib.md5(f"{os.path.relpath(path, ROOT)}#{variant}".encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "little"))


def crop_resize(img, ppg, ox, oy, rng, fmin, fmax):
    """Random crop offset + non-integer resize. Returns img, period, phase_x, phase_y."""
    cx, cy = int(rng.integers(0, int(ppg) + 1)), int(rng.integers(0, int(ppg) + 1))
    img = img[cy:, cx:]
    H, W = img.shape[:2]
    f = float(rng.uniform(fmin, fmax))
    f = min(f, 3000 / max(H, W))
    W2, H2 = max(64, round(W * f)), max(64, round(H * f))
    out = cv2.resize(img, (W2, H2), interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
    fx, fy = W2 / W, H2 / H
    # per-axis scale differs by rounding (<= 0.5 px over the image); GT uses each axis' own
    return out, ppg * fx, ppg * fy, ((ox - cx) * fx) % (ppg * fx), ((oy - cy) * fy) % (ppg * fy)


def blob_mask(shape, frac, rng):
    """Smooth random region covering `frac` of the image, soft 0..1 edges."""
    H, W = shape[:2]
    n = int(rng.integers(4, 9))
    low = rng.normal(size=(n, max(2, round(n * W / H)))).astype(np.float32)
    m = cv2.resize(low, (W, H), interpolation=cv2.INTER_CUBIC)
    m = (m > np.quantile(m, 1 - frac)).astype(np.float32)
    return cv2.GaussianBlur(m, (0, 0), 3)


def paint_grid(img, px, py, phx, phy, alpha, width, white, mask=None):
    """Anti-aliased lines centred at ph + k*p (continuous coords: pixel i = [i,i+1))."""
    H, W = img.shape[:2]

    def cover(n, p, ph):
        e = np.arange(n + 1, dtype=np.float64)
        c = np.zeros(n)
        for k in range(-1, int(n / p) + 2):
            a, b = ph + k * p - width / 2, ph + k * p + width / 2
            c += np.clip(np.minimum(e[1:], b) - np.maximum(e[:-1], a), 0, 1)
        return np.clip(c, 0, 1)

    m = np.maximum(cover(W, px, phx)[None, :], cover(H, py, phy)[:, None]) * alpha
    if mask is not None:
        m = m * mask
    tgt = 255.0 if white else 0.0
    out = img.astype(np.float32) * (1 - m[..., None]) + tgt * m[..., None]
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def make_item(item):
    kind, path, variant = item
    img, ppg, ox, oy = load(path)
    meta = {}
    if img is None:
        return None, None, meta
    if kind in ("real-vtt", "real-fa"):
        return img, (ppg, ppg, ox, oy), meta
    rng = rng_for(path, variant)
    if kind == "syn-xform":
        img, px, py, phx, phy = crop_resize(img, ppg, ox, oy, rng, 0.45, 1.15)
        return img, (px, py, phx, phy), meta
    if kind == "syn-misaligned":
        # a grid that has NOTHING to do with the map's own layout (tiles, walls)
        H, W = img.shape[:2]
        p = float(rng.uniform(max(24.0, min(H, W) / 45), min(H, W) / 9))
        phx, phy = float(rng.uniform(0, p)), float(rng.uniform(0, p))
        alpha = float(rng.uniform(0.15, 0.5))
        width = float(rng.choice([1.0, 1.5, 2.0, 3.0]))
        white = bool(rng.integers(0, 2))
        jpeg = int(rng.integers(60, 91)) if rng.integers(0, 2) else 0
        meta = {"alpha": round(alpha, 2), "width": width, "white": white, "jpeg": jpeg, "native": round(ppg, 2)}
        img = paint_grid(img, p, p, phx, phy, alpha, width, white)
        if jpeg:
            img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg])[1], cv2.IMREAD_COLOR)
        return img, (p, p, phx, phy), meta
    if kind == "syn-partial":
        img, px, py, phx, phy = crop_resize(img, ppg, ox, oy, rng, 0.7, 1.6)
        alpha = float(rng.uniform(0.2, 0.5))
        width = float(rng.choice([1.0, 1.5, 2.0]))
        white = bool(rng.integers(0, 2))
        frac = float(rng.uniform(0.35, 0.65))
        jpeg = int(rng.integers(60, 91)) if rng.integers(0, 2) else 0
        meta = {"alpha": round(alpha, 2), "width": width, "white": white, "frac": round(frac, 2), "jpeg": jpeg}
        img = paint_grid(img, px, py, phx, phy, alpha, width, white, blob_mask(img.shape, frac, rng))
        if jpeg:
            img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg])[1], cv2.IMREAD_COLOR)
        return img, (px, py, phx, phy), meta
    # syn-faint
    alpha = float(rng.uniform(0.1, 0.4))
    width = float(rng.choice([1.0, 1.5, 2.0]))
    white = bool(rng.integers(0, 2))
    after = bool(rng.integers(0, 2))        # resize AFTER painting (blurs the lines)
    jpeg = int(rng.integers(60, 91)) if rng.integers(0, 2) else 0
    meta = {"alpha": round(alpha, 2), "width": width, "white": white, "resize_after": after, "jpeg": jpeg}
    if after:
        cx, cy = int(rng.integers(0, int(ppg) + 1)), int(rng.integers(0, int(ppg) + 1))
        img = img[cy:, cx:]
        phx, phy = (ox - cx) % ppg, (oy - cy) % ppg
        img = paint_grid(img, ppg, ppg, phx, phy, alpha, width, white)
        H, W = img.shape[:2]
        f = float(rng.uniform(0.7, 1.3))
        W2, H2 = round(W * f), round(H * f)
        img = cv2.resize(img, (W2, H2), interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
        fx, fy = W2 / W, H2 / H
        px, py, phx, phy = ppg * fx, ppg * fy, phx * fx, phy * fy
    else:
        img, px, py, phx, phy = crop_resize(img, ppg, ox, oy, rng, 0.7, 1.6)
        img = paint_grid(img, px, py, phx, phy, alpha, width, white)
    if jpeg:
        img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg])[1], cv2.IMREAD_COLOR)
    return img, (px, py, phx, phy), meta


def line_dev(size, off, gp, gph, length):
    """Worst distance (in GT cells) of a predicted line from the nearest GT line."""
    xs = np.arange(off, length, size)
    d = np.abs(((xs - gph + gp / 2) % gp) - gp / 2)
    return float(d.max() / gp) if len(d) else 1.0


def judge(g, gt, shape):
    """g = dict with size/offset_x/offset_y. Returns (verdict, period_err, dev, phase_px)."""
    px, py, phx, phy = gt
    gp = (px + py) / 2
    H, W = shape[:2]
    perr = abs(g["size"] - gp) / gp
    if perr > 0.01:
        for q in (2, 3, 4, 1.5):
            if abs(g["size"] / (gp * q) - 1) < 0.015 or abs(g["size"] * q / gp - 1) < 0.015:
                return "harmonic", perr, None, None
        return "period", perr, None, None
    dev = max(line_dev(g["size"], g["offset_x"], px, phx, W), line_dev(g["size"], g["offset_y"], py, phy, H))
    cx = np.abs(((g["offset_x"] + round((W / 2 - g["offset_x"]) / g["size"]) * g["size"] - phx + px / 2) % px) - px / 2)
    cy = np.abs(((g["offset_y"] + round((H / 2 - g["offset_y"]) / g["size"]) * g["size"] - phy + py / 2) % py) - py / 2)
    return ("ok" if dev <= PHASE_TOL else "phase"), perr, dev, float(max(cx, cy))


def work(item):
    kind, path, variant = item
    rec = {"kind": kind, "path": os.path.relpath(path, ROOT), "variant": variant}
    try:
        img, gt, meta = make_item(item)
        if img is None:
            rec["error"] = "no image"
            return rec
        if "SAVE_DIR" in os.environ:        # debugging aid: dump the generated test image
            cv2.imwrite(os.path.join(os.environ["SAVE_DIR"], f"{kind}_{os.path.basename(path)}_{variant}.png"), img)
        t0 = time.perf_counter()
        g = grid_detect.detect_grid(img, debug=True)
        rec["time"] = time.perf_counter() - t0
        rec.update({"shape": list(img.shape[:2]), "gt": [round(v, 4) for v in gt], "meta": meta, "grid": g})
        est = g if g["found"] else g.get("candidate")
        if est:
            v, perr, dev, ph = judge(est, gt, img.shape)
            rec.update({"verdict": v, "perr": perr, "dev": dev, "phase_px": ph})
    except Exception as e:  # noqa: BLE001
        rec["error"] = repr(e)
    return rec


def summarize(recs, title):
    n = len(recs)
    if not n:
        return
    found = [r for r in recs if r["grid"]["found"]]
    ok = [r for r in found if r["verdict"] == "ok"]
    c = {v: sum(r["verdict"] == v for r in found) for v in ("harmonic", "period", "phase")}
    wrong = sum(c.values())
    miss = [r for r in recs if not r["grid"]["found"]]
    miss_ok = sum(r.get("verdict") == "ok" for r in miss)
    pe = np.array([r["perr"] for r in ok]) if ok else np.zeros(0)
    print(f"\n== {title}: {n} maps")
    print(f"  found            {len(found):4d}  ({100 * len(found) / n:.1f} %)")
    if found:
        nf = len(found)
        print(f"  of found: correct {len(ok):4d}  ({100 * len(ok) / nf:.1f} %)")
        print(f"     period err <0.2 % {int((pe < 0.002).sum()):4d} ({100 * (pe < 0.002).sum() / nf:.1f} %)"
              f"   <1 % {len(ok) + c['phase']:4d} ({100 * (len(ok) + c['phase']) / nf:.1f} %)")
        print(f"     CONFIDENTLY WRONG {wrong:4d}  (harmonic {c['harmonic']}, other period {c['period']}, "
              f"phase>{PHASE_TOL:.2f} cell {c['phase']})")
    if ok:
        ph = np.array([r["phase_px"] for r in ok])
        phf = np.array([r["phase_px"] / ((r["gt"][0] + r["gt"][1]) / 2) for r in ok])
        dv = np.array([r["dev"] for r in ok])
        print(f"     period err  median {100 * np.median(pe):.3f} %  p95 {100 * np.percentile(pe, 95):.3f} %  max {100 * pe.max():.3f} %")
        print(f"     phase err (image centre) median {np.median(ph):.2f} px = {np.median(phf):.4f} cell,"
              f"  p95 {np.percentile(ph, 95):.2f} px = {np.percentile(phf, 95):.4f} cell")
        print(f"     worst line deviation anywhere in the image: median {np.median(dv):.4f} cell, max {dv.max():.4f} cell")
    print(f"  not found        {len(miss):4d}  (of these the discarded best guess was right: {miss_ok})")
    for r in found:
        if r["verdict"] != "ok":
            g = r["grid"]
            print(f"    WRONG[{r['verdict']}] {r['path']}#{r['variant']} gt={r['gt'][0]:.2f} "
                  f"got={g['size']:.2f} off=({g['offset_x']:.1f},{g['offset_y']:.1f}) "
                  f"gtoff=({r['gt'][2]:.1f},{r['gt'][3]:.1f}) conf={g['confidence']} {r['meta']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=None, help="write per-map JSONL (features for threshold tuning)")
    ap.add_argument("--limit", type=int, default=0, help="only every N-th file (quick runs)")
    ap.add_argument("--sets", default="real-vtt,real-fa,syn-xform,syn-faint,syn-misaligned,syn-partial")
    ap.add_argument("--first-variant", type=int, default=0,
                    help="start of the synthetic variant numbers (use e.g. 100 for a fresh, unseen draw)")
    ap.add_argument("--xform-variants", type=int, default=3)
    ap.add_argument("--faint-variants", type=int, default=2)
    a = ap.parse_args()
    vtt = find_uvtt("vendor/vtt-maps", "corpus/real_uvtt")
    fa = find_uvtt("corpus/fa")
    if a.limit:
        vtt, fa = vtt[::a.limit], fa[::a.limit]
    sets = a.sets.split(",")
    items = []
    if "real-vtt" in sets:
        items += [("real-vtt", p, 0) for p in vtt]
    if "real-fa" in sets:
        items += [("real-fa", p, 0) for p in fa]
    if "syn-xform" in sets:
        items += [("syn-xform", p, a.first_variant + v) for p in vtt for v in range(a.xform_variants)]
    if "syn-faint" in sets:
        items += [("syn-faint", p, a.first_variant + v) for p in fa for v in range(a.faint_variants)]
    if "syn-misaligned" in sets:
        items += [("syn-misaligned", p, a.first_variant + v) for p in fa for v in range(1)]
    if "syn-partial" in sets:
        items += [("syn-partial", p, a.first_variant + v) for p in fa for v in range(1)]
    t0 = time.time()
    with Pool(a.workers) as pool:
        recs = pool.map(work, items, chunksize=2)
    errs = [r for r in recs if "error" in r]
    recs = [r for r in recs if "error" not in r]
    if a.out:
        with open(a.out, "w") as fh:
            for r in recs + errs:
                fh.write(json.dumps(r) + "\n")
    print(f"{len(items)} items, {len(errs)} errors, wall {time.time() - t0:.0f}s")
    for r in errs:
        print("  ERROR", r["path"], r["error"])
    for k in sets:
        summarize([r for r in recs if r["kind"] == k], k)
    faint = [r for r in recs if r["kind"] == "syn-faint"]
    if faint:
        print("\n== syn-faint recall by grid opacity (found & correct / all)")
        for lo, hi in ((0.1, 0.15), (0.15, 0.2), (0.2, 0.3), (0.3, 0.4001)):
            s = [r for r in faint if lo <= r["meta"]["alpha"] < hi]
            k = sum(r["grid"]["found"] and r["verdict"] == "ok" for r in s)
            print(f"  alpha {lo:.2f}-{hi:.2f}: {k}/{len(s)}")
        for name, key in (("white", True), ("black", False)):
            s = [r for r in faint if r["meta"]["white"] == key]
            k = sum(r["grid"]["found"] and r["verdict"] == "ok" for r in s)
            print(f"  {name}: {k}/{len(s)}")
    summarize(recs, "ALL")
    t = np.array([r["time"] for r in recs])
    print(f"\ndetect_grid time per map: median {np.median(t):.2f}s  p95 {np.percentile(t, 95):.2f}s  max {t.max():.2f}s"
          f"  (single-threaded, {a.workers} workers in parallel)")


if __name__ == "__main__":
    main()
