"""Deterministic folder-level split of the (licensed, local-only) Drakkenheim
map images into a held-out set (NEVER used for training) and a self-supervised
pool (for JEPA representation learning). Split by LOCATION folder so level
variants of the same place never straddle the split.
"""
import os, glob, random

ROOT = "corpus/drakkenheim/Drakkenheim Maps"
OUT = "corpus/drakkenheim_split"
HELDOUT_FRAC = 0.20
EXTS = (".webp", ".jpg", ".jpeg", ".png", ".JPG")


def all_images():
    by_loc = {}
    for p in glob.glob(f"{ROOT}/**/*", recursive=True):
        if not p.lower().endswith(tuple(e.lower() for e in EXTS)):
            continue
        if "UI module" in p:            # foundry ui assets, not maps
            continue
        rel = os.path.relpath(p, ROOT)
        loc = rel.split(os.sep)[0] if os.sep in rel else "_loose"
        by_loc.setdefault(loc, []).append(p)
    return by_loc


def main():
    os.makedirs(OUT, exist_ok=True)
    by_loc = all_images()
    total = sum(len(v) for v in by_loc.values())
    locs = sorted(by_loc)
    random.Random(0).shuffle(locs)
    heldout, ssl, acc = [], [], 0
    for loc in locs:
        imgs = by_loc[loc]
        if acc < HELDOUT_FRAC * total:
            heldout += imgs; acc += len(imgs)
        else:
            ssl += imgs
    heldout.sort(); ssl.sort()
    open(f"{OUT}/heldout_images.txt", "w").write("\n".join(heldout) + "\n")
    open(f"{OUT}/ssl_images.txt", "w").write("\n".join(ssl) + "\n")
    print(f"locations {len(locs)}  total imgs {total}")
    print(f"HELD-OUT (unused): {len(heldout)} imgs  ({100*len(heldout)//total}%)")
    print(f"SSL pool (JEPA):   {len(ssl)} imgs")


if __name__ == "__main__":
    main()
