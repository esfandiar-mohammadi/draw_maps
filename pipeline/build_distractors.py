"""Build a bank of NON-WALL patches for copy-paste augmentation (Ghiasi et al.,
CVPR 2021). Patches are cropped from the FA battlemaps' organic/decoration regions
(forest, water, furniture, floor texture) where the rasterized wall mask is empty
-- i.e. exactly the clutter the model currently misreads as walls. Pasting these
onto training tiles (mask unchanged) teaches wall-invariance to clutter.

Excludes fa_test maps. Saves RGBA-ish patches (BGR + soft alpha via feathering is
applied at paste time, so we store plain BGR crops + a 'floor-only' guarantee).
"""
import os, sys, glob, random
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt
from graph_eval_uvtt import raster, dil

OUT = "corpus/fa_distractors"
LONG_EDGE = 1024
N_PER_MAP = 14              # target patches per map
SIZES = [48, 64, 96, 128]  # square crop sizes (px at working scale)


def main():
    os.makedirs(OUT, exist_ok=True)
    test = set(ln.strip() for ln in open("corpus/fa_test.txt") if ln.strip())
    maps = sorted(glob.glob("corpus/fa/*.dd2vtt"))
    rng = random.Random(0)
    saved = 0
    for p in maps:
        slug = os.path.splitext(os.path.basename(p))[0]
        if slug in test:
            continue
        r = load_uvtt(p)
        if r["image"] is None or not r["walls"]:
            continue
        H0, W0 = r["image"].shape[:2]
        sc = min(1.0, LONG_EDGE / max(H0, W0))
        work = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        H, W = work.shape[:2]
        wall = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]], (H, W))
        forbid = dil(wall, 6)  # keep patches clear of walls (and their tolerance band)
        got = 0
        for _ in range(N_PER_MAP * 8):
            if got >= N_PER_MAP:
                break
            s = rng.choice(SIZES)
            if H <= s or W <= s:
                continue
            y = rng.randint(0, H - s); x = rng.randint(0, W - s)
            if forbid[y:y + s, x:x + s].any():
                continue  # overlaps a wall -> not a clean non-wall patch
            crop = work[y:y + s, x:x + s]
            if crop.std() < 6:  # skip near-flat blank patches (no useful clutter)
                continue
            cv2.imwrite(os.path.join(OUT, f"{slug}_{got:02d}.png"), crop)
            got += 1; saved += 1
    print(f"saved {saved} non-wall distractor patches to {OUT}", flush=True)


if __name__ == "__main__":
    main()
