#!/usr/bin/env python
"""Scaled, polite donjon harvester -> diverse BASE set of (image, wall_mask)
pairs. We fetch a few thousand distinct dungeons (NOT 200k: that many requests
would abuse a free service); the 200k training scale comes from augmentation.

grid=None so the renders carry no grid lines -> clean wall labels and no
grid=wall correlation. Grids are re-introduced synthetically at train time so the
model learns to IGNORE them.
"""
import os, sys, time, random, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np, cv2, requests

BASE = "https://donjon.bin.sh/fantasy/dungeon/preview.cgi"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
PRETTY = ["Parchment", "Slate", "Marble", "Sandstone", "Wooden", "Classic",
          "Crosshatch", "Steampunk", "Glacial", "Aquatic", "Infernal", "Asylum", "Gamma"]
LAYOUTS = ["Square", "Rectangle", "Box", "Cross", "Dagger", "Keep", "Round", "Cavernous"]
ROOMLAY = ["Sparse", "Scattered", "Dense"]
ROOMSZ = ["Small", "Medium", "Large"]
CORR = ["Labyrinth", "Errant", "Straight"]


def fetch(seed, params, style):
    q = dict(seed=seed, map_style=style, grid="None", dungeon_size="Medium",
             room_polymorph="Yes", door_set="Standard", remove_deadends="Some",
             add_stairs="Yes", peripheral_egress="", **params)
    for _ in range(2):
        try:
            r = requests.get(BASE, params=q, headers=UA, timeout=30)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                return cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            time.sleep(0.5)
    return None


def wall_mask(std):
    g = cv2.cvtColor(std, cv2.COLOR_BGR2GRAY)
    floor = (g > 110).astype(np.uint8)
    floor = cv2.morphologyEx(floor, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    grad = cv2.morphologyEx(floor, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    return cv2.dilate(grad, np.ones((2, 2), np.uint8)) * 255


def one(idx, out, rng_seed):
    rng = random.Random(rng_seed)
    seed = rng.randint(1, 2_000_000_000)
    params = dict(dungeon_layout=rng.choice(LAYOUTS), room_layout=rng.choice(ROOMLAY),
                  room_size=rng.choice(ROOMSZ), corridor_layout=rng.choice(CORR))
    style = rng.choice(PRETTY)
    std = fetch(seed, params, "Standard")
    inp = fetch(seed, params, style)
    if std is None or inp is None or std.shape != inp.shape:
        return False
    m = wall_mask(std)
    if m.mean() < 3 or m.mean() > 170:
        return False
    cv2.imwrite(f"{out}/images/{idx:06d}.png", inp)
    cv2.imwrite(f"{out}/masks/{idx:06d}.png", m)
    return True


def run(n, out, workers=6):
    os.makedirs(f"{out}/images", exist_ok=True)
    os.makedirs(f"{out}/masks", exist_ok=True)
    existing = len(os.listdir(f"{out}/images"))
    made = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for i in range(existing, existing + n * 2):
            futs[ex.submit(one, i, out, 7000 + i)] = i
            if len(futs) >= workers * 4:
                for f in as_completed(list(futs)):
                    if f.result():
                        made += 1
                    del futs[f]
                    if made % 100 == 0 and made:
                        print(f"  {made}/{n}", flush=True)
                    break
            if made >= n:
                break
        for f in as_completed(list(futs)):
            if f.result():
                made += 1
    total = len(os.listdir(f"{out}/images"))
    print(f"done: +{made} this run, {total} total in {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=2500)
    ap.add_argument("-o", "--out", default="corpus/donjon/base")
    ap.add_argument("-w", "--workers", type=int, default=6)
    a = ap.parse_args()
    run(a.n, a.out, a.workers)
