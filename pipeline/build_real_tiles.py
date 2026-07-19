#!/usr/bin/env python
"""Build REAL-domain training tiles to bridge the donjon->painted domain gap.

Two sources of painted-style (image, wall_mask) tiles:
  A) dd2vtt maps (train split; the 6 hard eval maps are EXCLUDED) with true GT
     walls -> rasterise, tile.
  B) Reddit maps -> PSEUDO labels where the CV grid stack and the SAM stack
     AGREE (high-confidence walls), per the confidence idea.
Tiles are produced at ~12 px/cell (matching donjon's scale) so wall thickness is
comparable across sources.
"""
import os, sys, glob, json, tempfile
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt

EVAL_NAMES = {"void-town", "goblin-travel-train", "desert-tavern", "road-side-in",
              "festival-of-fools", "little-fish-academy"}
TILE = 256
CELLPX = 12


def raster(segs, shape, thick):
    m = np.zeros(shape, np.uint8)
    for x0, y0, x1, y1 in segs:
        cv2.line(m, (int(x0), int(y0)), (int(x1), int(y1)), 255, thick)
    return m


def tile_and_save(img, mask, outimg, outmask, tag, stride=200, lo=0.004, hi=0.45):
    H, W = mask.shape
    n = 0
    for y in range(0, max(1, H - TILE) + 1, stride):
        for x in range(0, max(1, W - TILE) + 1, stride):
            mt = mask[y:y + TILE, x:x + TILE]
            it = img[y:y + TILE, x:x + TILE]
            if mt.shape[:2] != (TILE, TILE):
                continue
            frac = (mt > 127).mean()
            if frac < lo or frac > hi:
                continue
            cv2.imwrite(f"{outimg}/{tag}_{n:04d}.png", it)
            cv2.imwrite(f"{outmask}/{tag}_{n:04d}.png", mt)
            n += 1
    return n


def build_dd2vtt(outimg, outmask):
    total = 0
    paths = sorted(glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True))
    harvested = sorted(glob.glob("corpus/real_uvtt/**/*.dd2vtt", recursive=True)
                       + glob.glob("corpus/real_uvtt/**/*.uvtt", recursive=True))
    paths += [p for p in harvested if "_no_walls" not in p and "_dupes" not in p]
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        if name in EVAL_NAMES:
            continue
        tag = ("ru_" if "real_uvtt" in p else "dd_") + name[:16]
        try:
            r = load_uvtt(p)
        except Exception:
            continue
        if r["image"] is None or not r["walls"]:
            continue
        sc = CELLPX / r["ppg"]
        H0, W0 = r["image"].shape[:2]
        if max(H0 * sc, W0 * sc) < TILE:
            sc = TILE / min(H0, W0)
        img = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        segs = [(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]]
        # LEARNED THICKNESS: label = wall FOOTPRINT (dark wall material around the GT
        # centerline), so the true, varying wall width is captured, not a fixed line.
        cl = raster(segs, img.shape[:2], thick=2)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        dark = (gray < np.percentile(gray, 45)).astype(np.uint8)
        maxthick = max(6, int(CELLPX * 1.3))
        near = cv2.dilate(cl, np.ones((maxthick, maxthick), np.uint8))
        footprint = ((near > 0) & (dark > 0)).astype(np.uint8)
        footprint = (footprint | (cl > 0)).astype(np.uint8) * 255
        footprint = cv2.morphologyEx(footprint, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        total += tile_and_save(img, footprint, outimg, outmask, tag, hi=0.6)
    print("dd2vtt tiles:", total)
    return total


def build_fa(outimg, outmask):
    """Forgotten-Adventures maps -> footprint wall-mask tiles. Excludes the 20%
    held-out FA test maps (corpus/fa_test.txt). Same scale/thickness convention
    as build_dd2vtt so FA tiles mix cleanly with donjon/dd2vtt."""
    fa_test = set()
    if os.path.exists("corpus/fa_test.txt"):
        fa_test = {ln.strip() for ln in open("corpus/fa_test.txt") if ln.strip()}
    total = 0
    for p in sorted(glob.glob("corpus/fa/*.dd2vtt")):
        name = os.path.splitext(os.path.basename(p))[0]
        if name in fa_test:
            continue
        try:
            r = load_uvtt(p)
        except Exception:
            continue
        if r["image"] is None or not r["walls"]:
            continue
        sc = CELLPX / r["ppg"]
        H0, W0 = r["image"].shape[:2]
        if max(H0 * sc, W0 * sc) < TILE:
            sc = TILE / min(H0, W0)
        img = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        segs = [(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]]
        cl = raster(segs, img.shape[:2], thick=2)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        dark = (gray < np.percentile(gray, 45)).astype(np.uint8)
        maxthick = max(6, int(CELLPX * 1.3))
        near = cv2.dilate(cl, np.ones((maxthick, maxthick), np.uint8))
        footprint = ((near > 0) & (dark > 0)).astype(np.uint8)
        footprint = (footprint | (cl > 0)).astype(np.uint8) * 255
        footprint = cv2.morphologyEx(footprint, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        total += tile_and_save(img, footprint, outimg, outmask, "fa_" + name[:20], hi=0.6)
    print("FA tiles:", total)
    return total


def build_reddit_pseudo(outimg, outmask):
    import grid_walls, sam_walls
    total = 0
    for p in sorted(glob.glob("corpus/maps/map0*.jpeg") + glob.glob("corpus/maps/map0*.png")):
        name = os.path.basename(p).split("_")[0]
        if name in {"map04", "map05", "map06"}:   # not battlemaps
            continue
        with tempfile.TemporaryDirectory() as td:
            try:
                mcv = grid_walls.run(p, f"{td}/cv", work_edge=1024)
                msam = sam_walls.run(p, f"{td}/sam", work_edge=1024, use_classifier=True)
            except Exception as e:
                print("  reddit fail", name, str(e)[:60]); continue
            if mcv is None or msam is None:
                continue
            Ww, Hh = msam["work_size"]
            cvw = [tuple(w["c"]) for w in json.load(open(f"{td}/cv/walls.json"))] if os.path.exists(f"{td}/cv/walls.json") else []
            saw = [tuple(w["c"]) for w in json.load(open(f"{td}/sam/walls.json"))] if os.path.exists(f"{td}/sam/walls.json") else []
            if not cvw or not saw:
                continue
            cvm = raster(cvw, (Hh, Ww), 2); sam = raster(saw, (Hh, Ww), 2)
            k = 7
            agree = (cvm > 0) & (cv2.dilate(sam, np.ones((k, k), np.uint8)) > 0)
            mask = (agree.astype(np.uint8) * 255)
            mask = cv2.dilate(mask, np.ones((2, 2), np.uint8))
            img = cv2.imread(f"{td}/sam/bg.webp")
            total += tile_and_save(img, mask, outimg, outmask, "rd_" + name, lo=0.002)
    print("reddit pseudo tiles:", total)
    return total


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["dd2vtt", "reddit", "fa"], default=None,
                    help="build only one source")
    ap.add_argument("--out", default="corpus/real", help="output tile dir")
    a = ap.parse_args()
    outimg, outmask = f"{a.out}/images", f"{a.out}/masks"
    os.makedirs(outimg, exist_ok=True)
    os.makedirs(outmask, exist_ok=True)
    if a.only == "fa":
        build_fa(outimg, outmask)
    elif a.only == "dd2vtt":
        build_dd2vtt(outimg, outmask)
    elif a.only == "reddit":
        build_reddit_pseudo(outimg, outmask)
    else:
        build_dd2vtt(outimg, outmask)
        build_reddit_pseudo(outimg, outmask)
    print("total tiles:", len(os.listdir(outimg)))


if __name__ == "__main__":
    main()
