#!/usr/bin/env python
"""Generate UNLIMITED labelled training data from donjon.

Trick: the same seed+params renders identical geometry in any map_style. We
fetch two renders per dungeon:
  - map_style=Standard  -> bright floor on black rock -> derive the wall mask
    (boundary of the floor region; doorways are gaps so they stay open)
  - a random "pretty" style -> the training INPUT image
Same seed => pixel-aligned (image, wall_mask) pair. Vary seed + layout + style
for diversity.
"""
import os, sys, time, io, random, argparse
import numpy as np, cv2, requests

BASE = "https://donjon.bin.sh/fantasy/dungeon/preview.cgi"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
PRETTY = ["Parchment", "Slate", "Marble", "Sandstone", "Wooden", "Classic",
          "Crosshatch", "Steampunk", "Glacial", "Aquatic", "Infernal", "Asylum"]
LAYOUTS = ["Square", "Rectangle", "Box", "Cross", "Dagger", "Keep", "Round", "Cavernous"]
ROOMLAY = ["Sparse", "Scattered", "Dense"]
ROOMSZ = ["Small", "Medium", "Large"]
CORR = ["Labyrinth", "Errant", "Straight"]


def fetch(seed, params, style):
    q = dict(seed=seed, map_style=style, grid="Square", dungeon_size="Medium",
             room_polymorph="Yes", door_set="Standard", remove_deadends="Some",
             add_stairs="Yes", peripheral_egress="", **params)
    for _ in range(3):
        try:
            r = requests.get(BASE, params=q, headers=UA, timeout=30)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                arr = np.frombuffer(r.content, np.uint8)
                return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            time.sleep(1.0)
    return None


def wall_mask_from_standard(std):
    g = cv2.cvtColor(std, cv2.COLOR_BGR2GRAY)
    floor = (g > 110).astype(np.uint8)
    floor = cv2.morphologyEx(floor, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    grad = cv2.morphologyEx(floor, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    return cv2.dilate(grad, np.ones((2, 2), np.uint8)) * 255


def run(n, out):
    os.makedirs(f"{out}/images", exist_ok=True)
    os.makedirs(f"{out}/masks", exist_ok=True)
    rng = random.Random(1234)
    made = 0
    for i in range(n * 2):
        if made >= n:
            break
        seed = rng.randint(1, 2_000_000_000)
        params = dict(dungeon_layout=rng.choice(LAYOUTS), room_layout=rng.choice(ROOMLAY),
                      room_size=rng.choice(ROOMSZ), corridor_layout=rng.choice(CORR))
        style = rng.choice(PRETTY)
        std = fetch(seed, params, "Standard")
        inp = fetch(seed, params, style)
        time.sleep(0.25)
        if std is None or inp is None or std.shape != inp.shape:
            continue
        mask = wall_mask_from_standard(std)
        if mask.mean() < 3 or mask.mean() > 160:   # skip degenerate
            continue
        cv2.imwrite(f"{out}/images/{made:04d}.png", inp)
        cv2.imwrite(f"{out}/masks/{made:04d}.png", mask)
        made += 1
        if made % 25 == 0:
            print(f"  {made}/{n} pairs", flush=True)
    print(f"done: {made} pairs -> {out}")
    return made


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("-o", "--out", default="corpus/donjon/dataset")
    a = ap.parse_args()
    run(a.n, a.out)
