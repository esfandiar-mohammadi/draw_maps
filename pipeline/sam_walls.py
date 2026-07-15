#!/usr/bin/env python
"""SAM-based wall detection: segment REGIONS with a pretrained Segment-Anything
model, take the boundaries between walkable regions as candidate walls, then run
the existing grid post-processing (snap to grid, merge, weld, prune).

Rationale: SAM segments coherent regions (rooms, floor areas), not thin lines.
Walls are exactly the borders between adjacent regions. This sidesteps the hand-
tuned darkness/edge heuristics; the grid code we already have turns the region
borders into clean, connected, grid-snapped Foundry walls.

Model: uses Ultralytics FastSAM/SAM (prompt-free automatic segmentation). Falls
back across a couple of checkpoints. Requires torch + ultralytics in the venv.
"""
import os, sys, json, argparse
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grid_detect import run as detect_grid          # noqa: E402
from grid_walls import (edge_line_stats, merge_runs, weld_endpoints,      # noqa: E402
                        prune_isolated, foundry_wall)

_CLF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "region_clf.joblib")


def _load_clf():
    try:
        import joblib
        return joblib.load(_CLF_PATH)
    except Exception:
        return None


def prop_flags(masks, work, drop_thr=0.80):
    """Return a boolean per mask: True if the learned classifier is confident
    the region is a PROP (not a wall boundary) and it should be dropped."""
    from region_classifier import region_features, FEATS
    bundle = _load_clf()
    if bundle is None:
        return [False] * len(masks)
    clf = bundle["clf"]
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY).astype(np.float32)
    d = 255 - gray
    dark = np.clip((d - np.percentile(d, 50)) / (np.percentile(d, 99) - np.percentile(d, 50) + 1e-6), 0, 1)
    prop_idx = list(clf.classes_).index(0)
    flags = []
    for m in masks:
        f = region_features(m, work, hsv, dark)
        if f is None:
            flags.append(False); continue
        p_prop = clf.predict_proba([[f[k] for k in FEATS]])[0][prop_idx]
        flags.append(p_prop >= drop_thr)
    return flags


def sam_masks(work, model_name="FastSAM-x.pt", imgsz=1024, device=0):
    """Return a list of binary region masks (uint8 HxW) via Ultralytics."""
    from ultralytics import FastSAM
    model = FastSAM(model_name)
    res = model(work, imgsz=imgsz, device=device, retina_masks=True,
                conf=0.4, iou=0.9, verbose=False)
    out = []
    r = res[0]
    if r.masks is None:
        return out
    for m in r.masks.data.cpu().numpy():
        out.append((m > 0.5).astype(np.uint8))
    return out


def boundary_wallness(masks, shape, min_area_frac=0.002, max_area_frac=0.9):
    """Accumulate region-boundary pixels into a [0,1] wall-ness map. Drop tiny
    masks (decor/props) and near-full-image masks (background)."""
    H, W = shape
    total = H * W
    acc = np.zeros((H, W), np.float32)
    kept = 0
    for m in masks:
        a = int(m.sum())
        if a < min_area_frac * total or a > max_area_frac * total:
            continue
        kept += 1
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(acc, cnts, -1, 1.0, thickness=2)
    if acc.max() > 0:
        acc = np.clip(acc, 0, 1)
    return acc, kept


def run(inp, out, work_edge=1536, band=3, k=1.0, cov_min=0.5, gap_close=1,
        weld=1, prune=2, min_conf=3.0, model_name="FastSAM-x.pt",
        min_contrast=0.10, dark_bias=True, use_classifier=True, drop_thr=0.80):
    os.makedirs(out, exist_ok=True)
    g = detect_grid(inp)
    img = cv2.imread(inp, cv2.IMREAD_COLOR)
    H0, W0 = img.shape[:2]
    scale = min(1.0, work_edge / max(H0, W0))
    work = cv2.resize(img, (round(W0 * scale), round(H0 * scale)),
                      interpolation=cv2.INTER_AREA) if scale < 1 else img.copy()
    Hh, Ww = work.shape[:2]

    masks = sam_masks(work, model_name=model_name)
    if use_classifier:
        flags = prop_flags(masks, work, drop_thr=drop_thr)
        n_dropped = int(sum(flags))
        masks = [m for m, fl in zip(masks, flags) if not fl]
    else:
        n_dropped = 0
    wm, kept = boundary_wallness(masks, (Hh, Ww))
    if dark_bias:
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY).astype(np.float32)
        dark = 255.0 - gray
        lo, hi = np.percentile(dark, 50), np.percentile(dark, 99)
        dark = np.clip((dark - lo) / (hi - lo + 1e-6), 0, 1)
        wm = wm * (0.5 + 0.5 * dark)   # prefer boundaries that are also dark

    if g["conf"] < min_conf:
        # No reliable grid: emit region boundaries directly as (unsnapped) walls
        json.dump({"input": os.path.basename(inp), "used_grid": False,
                   "n_masks": len(masks), "kept": kept},
                  open(os.path.join(out, "metrics.json"), "w"), indent=1)
        print(json.dumps({"input": os.path.basename(inp), "used_grid": False,
                          "n_masks": len(masks), "kept": kept}))
        return

    gs = g["grid"] * scale
    ox = (g["offset_x"] * scale) % gs
    oy = (g["offset_y"] * scale) % gs
    xs = np.arange(ox, Ww - 1, gs)
    ys = np.arange(oy, Hh - 1, gs)
    nx, ny = len(xs), len(ys)

    Hs = np.zeros((ny, nx - 1)); Hcov = np.zeros((ny, nx - 1))
    for j in range(ny):
        for i in range(nx - 1):
            Hs[j, i], Hcov[j, i] = edge_line_stats(
                wm, (xs[i], ys[j]), (xs[i + 1], ys[j]), band, True)
    Vs = np.zeros((nx, ny - 1)); Vcov = np.zeros((nx, ny - 1))
    for i in range(nx):
        for j in range(ny - 1):
            Vs[i, j], Vcov[i, j] = edge_line_stats(
                wm, (xs[i], ys[j]), (xs[i], ys[j + 1]), band, False)

    allc = np.concatenate([Hs.ravel(), Vs.ravel()])
    med = float(np.median(allc)); mad = float(np.median(np.abs(allc - med))) + 1e-6
    thr = max(min_contrast, med + k * 1.4826 * mad)
    Hflag = (Hs >= thr) & (Hcov >= cov_min)
    Vflag = (Vs >= thr) & (Vcov >= cov_min)

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
    metrics = {"input": os.path.basename(inp), "used_grid": True,
               "grid_orig_px": g["grid"], "n_masks": len(masks), "kept_masks": kept, "props_dropped": n_dropped,
               "work_size": [Ww, Hh], "n_walls": len(walls),
               "total_wall_len_px": round(tot, 1), "threshold": round(thr, 3)}
    json.dump(metrics, open(os.path.join(out, "metrics.json"), "w"), indent=1)
    print(json.dumps(metrics))
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--work-edge", type=int, default=1536)
    ap.add_argument("--model", default="FastSAM-x.pt")
    ap.add_argument("--k", type=float, default=1.0)
    a = ap.parse_args()
    run(a.input, a.out, a.work_edge, k=a.k, model_name=a.model)
