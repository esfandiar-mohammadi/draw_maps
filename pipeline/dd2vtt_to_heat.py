"""Convert our dd2vtt/uvtt ground truth into HEAT's S3D-floorplan training
format (see vendor/heat/datasets/s3d_floorplans.py):

  corpus/heat_data/
    density/<name>.png   256x256 crop of the map (working scale: long edge 1024)
    normals/<name>.png   black (dataset does max(density, normals))
    annot/<name>.npy     pickled dict {(x,y): [np.array([x2,y2]), ...]} — planar
                         graph: corner -> connected corners, both directions
    train_list.txt / valid_list.txt / test_list.txt

Sources: vendor/vtt-maps (all dd2vtt with walls) + corpus/real_uvtt/**.
The 6 held-out hard eval maps are EXCLUDED. Per map: sliding 256 crops
(stride 128) that contain enough wall, corners merged within 3 px, segments
clipped to the crop, corners clipped to [1, 254] (get_corner_labels indexes a
256 array with rounded coords; random_flip uses size-x).
"""
import os, sys, glob, argparse, random
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt  # noqa: E402

HARD = {"void-town", "goblin-travel-train", "desert-tavern", "road-side-in",
        "festival-of-fools", "little-fish-academy"}


def clip_seg(x0, y0, x1, y1, lo, hi):
    """Liang-Barsky clip of segment to square [lo,hi]^2; None if outside."""
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - lo), (dx, hi - x0), (-dy, y0 - lo), (dy, hi - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    if t0 >= t1:
        return None
    return (x0 + t0 * dx, y0 + t0 * dy, x0 + t1 * dx, y0 + t1 * dy)


def crop_annot(walls, cx, cy, size=256, merge_tol=3.0, min_len=60.0):
    """Wall segments (map working coords) -> annot dict for crop at (cx,cy).
    Returns (annot, total_len) or (None, 0) if the crop is unusable."""
    pts, edges, total = [], set(), 0.0

    def corner_id(x, y):
        x = min(max(x, 1.0), size - 2.0); y = min(max(y, 1.0), size - 2.0)
        for i, (px, py) in enumerate(pts):
            if (px - x) ** 2 + (py - y) ** 2 <= merge_tol ** 2:
                return i
        pts.append((x, y)); return len(pts) - 1

    for x0, y0, x1, y1 in walls:
        c = clip_seg(x0 - cx, y0 - cy, x1 - cx, y1 - cy, 0.0, size - 1.0)
        if c is None:
            continue
        a, b = corner_id(c[0], c[1]), corner_id(c[2], c[3])
        if a == b:
            continue
        edges.add((min(a, b), max(a, b)))
        total += float(np.hypot(c[2] - c[0], c[3] - c[1]))
    if total < min_len or not (2 <= len(pts) <= 100) or len(edges) < 2:
        return None, total
    annot = {p: [] for p in pts}
    for a, b in edges:
        annot[pts[a]].append(np.array(pts[b]))
        annot[pts[b]].append(np.array(pts[a]))
    return annot, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="corpus/heat_data")
    ap.add_argument("--long_edge", type=int, default=1024)
    ap.add_argument("--crop", type=int, default=256)
    ap.add_argument("--stride", type=int, default=128)
    ap.add_argument("--max_per_map", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fa", action="store_true",
                    help="also include Forgotten-Adventures maps (corpus/fa/*.dd2vtt)")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    files = sorted(glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True))
    for ext in ("dd2vtt", "uvtt", "json"):
        files += sorted(glob.glob(f"corpus/real_uvtt/**/*.{ext}", recursive=True))
    fa_test = set()
    if args.fa:
        files += sorted(glob.glob("corpus/fa/**/*.dd2vtt", recursive=True))
        if os.path.exists("corpus/fa_test.txt"):
            fa_test = {ln.strip() for ln in open("corpus/fa_test.txt") if ln.strip()}
            print(f"holding out {len(fa_test)} FA maps as test (corpus/fa_test.txt)")
    for d in ("density", "normals", "annot"):
        os.makedirs(os.path.join(args.out, d), exist_ok=True)
    black = np.zeros((args.crop, args.crop, 3), np.uint8)

    names_by_map, n_maps, n_skip = {}, 0, 0
    for fi, path in enumerate(files):
        stem = os.path.splitext(os.path.basename(path))[0]
        if stem in HARD or stem in fa_test:
            continue
        try:
            r = load_uvtt(path)
        except Exception as e:
            print(f"SKIP unparseable {path}: {e}"); n_skip += 1; continue
        if r["image"] is None or not r["walls"]:
            n_skip += 1; continue
        H0, W0 = r["image"].shape[:2]
        sc = min(1.0, args.long_edge / max(H0, W0))
        work = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)),
                          interpolation=cv2.INTER_AREA)
        walls = [(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]]
        H, W = work.shape[:2]
        cand = [(x, y) for y in range(0, max(1, H - args.crop + 1), args.stride)
                for x in range(0, max(1, W - args.crop + 1), args.stride)]
        rng.shuffle(cand)
        mapkey = f"m{fi:03d}_{stem}"[:60].replace(" ", "_")
        names = []
        for cx, cy in cand:
            if len(names) >= args.max_per_map:
                break
            crop = work[cy:cy + args.crop, cx:cx + args.crop]
            if crop.shape[0] < args.crop or crop.shape[1] < args.crop:
                continue
            annot, _ = crop_annot(walls, cx, cy, size=args.crop)
            if annot is None:
                continue
            name = f"{mapkey}_y{cy}_x{cx}"
            cv2.imwrite(os.path.join(args.out, "density", name + ".png"), crop)
            cv2.imwrite(os.path.join(args.out, "normals", name + ".png"), black)
            np.save(os.path.join(args.out, "annot", name + ".npy"), annot)
            names.append(name)
        if names:
            names_by_map[mapkey] = names; n_maps += 1
            print(f"{mapkey}: {len(names)} crops")

    # split by MAP (no crop-level leakage): every 12th map -> valid
    keys = sorted(names_by_map)
    train, valid = [], []
    for i, k in enumerate(keys):
        (valid if i % 12 == 5 else train).extend(names_by_map[k])
    rng.shuffle(train)
    for fn, lst in (("train_list.txt", train), ("valid_list.txt", valid),
                    ("test_list.txt", valid)):
        with open(os.path.join(args.out, fn), "w") as f:
            f.writelines(n + "\n" for n in lst)
    print(f"\n{n_maps} maps used, {n_skip} skipped -> "
          f"{len(train)} train / {len(valid)} valid crops in {args.out}")


if __name__ == "__main__":
    main()
