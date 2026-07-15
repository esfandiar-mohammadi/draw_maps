#!/usr/bin/env python
"""In-domain 'what is NOT a wall' filter for the SAM pipeline.

SAM segments a battlemap into regions. Room/floor/structure regions have
boundaries that ARE walls; prop/object regions (rugs, carts, stalls, plants)
have boundaries that are NOT walls and cause false positives. We can't download
FA's categorised assets (Patreon), so we bootstrap labels IN-DOMAIN from the
corpus: each SAM region gets shape/colour features and a weak label, then a
RandomForest learns prop-vs-keep. The trained model filters regions in
sam_walls before boundaries are turned into walls.

Weak labelling rule (only confident regions are used for training; ambiguous
ones are skipped):
  PROP  (0): medium/small AND (irregular shape OR saturated colour OR extreme aspect)
  KEEP  (1): large AND rectangular AND low saturation   (room / floor / structure)
"""
import os, sys, json, glob
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sam_walls import sam_masks   # noqa: E402

FEATS = ["area_frac", "extent", "solidity", "aspect", "sat", "val", "val_std", "bnd_dark"]


def region_features(m, work, hsv, dark):
    a = int(m.sum())
    H, W = m.shape
    ys, xs = np.where(m)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bw, bh = (x1 - x0 + 1), (y1 - y0 + 1)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    hull = cv2.contourArea(cv2.convexHull(c)) + 1e-6
    inner = cv2.erode(m, np.ones((3, 3), np.uint8), iterations=2).astype(bool)
    if inner.sum() < 10:
        inner = m.astype(bool)
    bnd = (cv2.dilate(m, np.ones((3, 3), np.uint8), 2) - cv2.erode(m, np.ones((3, 3), np.uint8), 1)).astype(bool)
    return {
        "area_frac": a / (H * W),
        "extent": a / (bw * bh),
        "solidity": a / hull,
        "aspect": max(bw, bh) / min(bw, bh),
        "sat": float(hsv[:, :, 1][inner].mean()) / 255.0,
        "val": 1.0 - float(hsv[:, :, 2][inner].mean()) / 255.0,
        "val_std": float(hsv[:, :, 2][inner].std()) / 255.0,
        "bnd_dark": float(dark[bnd].mean()) if bnd.sum() else 0.0,
    }


def weak_label(f):
    """Return 1 (keep/room), 0 (prop/not-wall), or None (ambiguous)."""
    if f["area_frac"] > 0.012 and f["extent"] > 0.62 and f["sat"] < 0.35:
        return 1
    if (0.0006 < f["area_frac"] < 0.012 and
            (f["solidity"] < 0.82 or f["sat"] > 0.45 or f["aspect"] > 3.5)):
        return 0
    return None


def harvest(map_paths, work_edge=1536):
    X, y = [], []
    for p in map_paths:
        img = cv2.imread(p)
        if img is None:
            continue
        H0, W0 = img.shape[:2]
        sc = min(1.0, work_edge / max(H0, W0))
        work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY).astype(np.float32)
        dark = np.clip((255 - gray - np.percentile(255 - gray, 50)) /
                       (np.percentile(255 - gray, 99) - np.percentile(255 - gray, 50) + 1e-6), 0, 1)
        masks = sam_masks(work)
        n_lab = 0
        for m in masks:
            f = region_features(m, work, hsv, dark)
            if f is None:
                continue
            lab = weak_label(f)
            if lab is None:
                continue
            X.append([f[k] for k in FEATS]); y.append(lab); n_lab += 1
        print(f"  {os.path.basename(p)}: {len(masks)} masks, {n_lab} weak-labelled")
    return np.array(X), np.array(y)


def main():
    maps = sorted(glob.glob("corpus/maps/map0*.jpeg") + glob.glob("corpus/maps/map0*.png"))
    # drop the non-battlemaps (illustration, region maps) for cleaner labels
    maps = [m for m in maps if not any(s in m for s in ["map04", "map05", "map06"])]
    print("harvesting from:", [os.path.basename(m) for m in maps])
    X, y = harvest(maps)
    print(f"total weak-labelled regions: {len(y)}  (keep={int((y==1).sum())}, prop={int((y==0).sum())})")
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    clf = RandomForestClassifier(n_estimators=200, max_depth=8, class_weight="balanced", random_state=0)
    if len(set(y)) == 2:
        cv = cross_val_score(clf, X, y, cv=5)
        print("5-fold CV acc:", np.round(cv, 3), "mean", round(cv.mean(), 3))
    clf.fit(X, y)
    print("feature importance:", dict(zip(FEATS, np.round(clf.feature_importances_, 3))))
    import joblib
    os.makedirs("pipeline/models", exist_ok=True)
    joblib.dump({"clf": clf, "feats": FEATS}, "pipeline/models/region_clf.joblib")
    print("saved pipeline/models/region_clf.joblib")


if __name__ == "__main__":
    main()
