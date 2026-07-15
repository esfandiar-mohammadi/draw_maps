#!/usr/bin/env python
"""Characterise WHERE the wall detection is error-free, to mine high-confidence
pseudo-labels for ML training.

Idea (user's): the CV stack is unreliable overall, but where two INDEPENDENT
detectors agree it should be nearly error-free. We run the CV grid stack and the
SAM stack (both grid-snapped to the same grid) and measure, against UVTT ground
truth, the precision of:
  - CV walls alone
  - SAM walls alone
  - AGREEMENT (walls both detectors produce)  <- the high-confidence set
If agreement precision is high, those walls are trustworthy training labels even
on maps where overall accuracy is poor.
"""
import os, sys, json, glob, tempfile
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grid_walls, sam_walls              # noqa: E402
from uvtt import load as load_uvtt        # noqa: E402


def raster(segs, shape, thick=1):
    m = np.zeros(shape, np.uint8)
    for x0, y0, x1, y1 in segs:
        cv2.line(m, (int(x0), int(y0)), (int(x1), int(y1)), 255, thick)
    return m > 0


def dil(mask, tol):
    k = 2 * int(tol) + 1
    return cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0


def load_walls(js):
    return [tuple(w["c"]) for w in json.load(open(js))] if os.path.exists(js) else []


def analyse(path, work_edge=1536):
    r = load_uvtt(path)
    if r["image"] is None or not r["walls"]:
        return None
    H0, W0 = r["image"].shape[:2]
    sc = min(1.0, work_edge / max(H0, W0))
    gt_segs = [(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]]
    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, "m.png"); cv2.imwrite(png, r["image"])
        mcv = grid_walls.run(png, os.path.join(td, "cv"), work_edge=work_edge)
        msam = sam_walls.run(png, os.path.join(td, "sam"), work_edge=work_edge, use_classifier=False)
        if mcv is None or msam is None:
            return None
        Ww, Hh = msam["work_size"]
        cv_segs = load_walls(os.path.join(td, "cv", "walls.json"))
        sam_segs = load_walls(os.path.join(td, "sam", "walls.json"))
        if not cv_segs or not sam_segs:
            return None
        tol = max(4, 0.4 * r["ppg"] * sc)
        gt = raster(gt_segs, (Hh, Ww)); gt_d = dil(gt, tol)
        cvm = raster(cv_segs, (Hh, Ww)); samm = raster(sam_segs, (Hh, Ww))
        agree = cvm & dil(samm, tol)          # CV walls confirmed by SAM
        def prec(m):
            return float((m & gt_d).sum()) / float(m.sum()) if m.sum() else 0.0
        # recall of the high-confidence set: how much of GT it covers
        rec_agree = float((gt & dil(agree, tol)).sum()) / float(gt.sum()) if gt.sum() else 0.0
        return {"P_cv": round(prec(cvm), 3), "P_sam": round(prec(samm), 3),
                "P_agree": round(prec(agree), 3), "R_agree": round(rec_agree, 3),
                "px_cv": int(cvm.sum()), "px_agree": int(agree.sum())}


def main():
    # a spread including harder, prop-heavy maps
    want = ["mountain-town-tavern-with-cabins", "road-side-in", "desert-tavern",
            "festival-of-fools", "little-fish-academy", "void-town", "goblin-travel-train"]
    allp = glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True)
    picked = [p for n in want for p in allp if os.path.basename(p) == n + ".dd2vtt"]
    rows = []
    for p in picked:
        r = analyse(p)
        name = os.path.basename(p).replace(".dd2vtt", "")
        if r is None:
            print(f"{name:38s} skipped"); continue
        print(f"{name:38s} P_cv={r['P_cv']:.2f} P_sam={r['P_sam']:.2f} "
              f"P_AGREE={r['P_agree']:.2f} (covers R={r['R_agree']:.2f} of GT)")
        rows.append(r)
    if rows:
        import numpy as np
        print(f"\nMEAN  P_cv={np.mean([r['P_cv'] for r in rows]):.3f}  "
              f"P_sam={np.mean([r['P_sam'] for r in rows]):.3f}  "
              f"P_AGREE={np.mean([r['P_agree'] for r in rows]):.3f}  "
              f"R_agree={np.mean([r['R_agree'] for r in rows]):.3f}")


if __name__ == "__main__":
    main()
