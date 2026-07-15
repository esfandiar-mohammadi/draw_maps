#!/usr/bin/env python
"""Measure the SAM wall pipeline against UVTT ground truth (precision/recall),
with the region classifier ON vs OFF. Length-based with a tolerance band."""
import os, sys, json, glob, tempfile
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sam_walls                       # noqa: E402
from uvtt import load as load_uvtt     # noqa: E402


def rasterize(segs, shape, thick=1):
    m = np.zeros(shape, np.uint8)
    for x0, y0, x1, y1 in segs:
        cv2.line(m, (int(x0), int(y0)), (int(x1), int(y1)), 255, thick)
    return m > 0


def prf(pred_segs, gt_segs, shape, tol):
    pred = rasterize(pred_segs, shape)
    gt = rasterize(gt_segs, shape)
    if pred.sum() == 0 or gt.sum() == 0:
        return 0.0, 0.0, 0.0
    k = 2 * int(tol) + 1
    gt_d = cv2.dilate(gt.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    pred_d = cv2.dilate(pred.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    precision = float((pred & gt_d).sum()) / float(pred.sum())
    recall = float((gt & pred_d).sum()) / float(gt.sum())
    f1 = 2 * precision * recall / (precision + recall + 1e-9)
    return round(precision, 3), round(recall, 3), round(f1, 3)


def eval_map(path, work_edge=1536):
    r = load_uvtt(path)
    if r["image"] is None or not r["walls"]:
        return None
    H0, W0 = r["image"].shape[:2]
    sc = min(1.0, work_edge / max(H0, W0))
    gt_segs = [(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]]
    with tempfile.TemporaryDirectory() as td:
        png = os.path.join(td, "map.png")
        cv2.imwrite(png, r["image"])
        res = {}
        for tag, use in [("no_clf", False), ("with_clf", True)]:
            od = os.path.join(td, tag)
            m = sam_walls.run(png, od, work_edge=work_edge, use_classifier=use)
            wj = os.path.join(od, "walls.json")
            if m is None or not os.path.exists(wj):
                return None  # no grid -> skip map
            walls = json.load(open(wj))
            pred = [tuple(w["c"]) for w in walls]
            Ww, Hh = m["work_size"]
            tol = max(4, 0.4 * r["ppg"] * sc)
            p, rc, f1 = prf(pred, gt_segs, (Hh, Ww), tol)
            res[tag] = {"P": p, "R": rc, "F1": f1, "n_walls": m["n_walls"],
                        "props_dropped": m.get("props_dropped", 0)}
    return res


def main():
    test = ["desert-tavern", "void-town", "road-side-in", "Red Tower - Base", "headmasters-quarters"]
    allp = glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True)
    picked = [p for name in test for p in allp if os.path.basename(p) == name + ".dd2vtt"]
    rows = []
    for p in picked:
        r = eval_map(p)
        name = os.path.basename(p)
        if r is None:
            print(f"{name:35s} skipped (no grid / no walls)"); continue
        print(f"{name:35s} noClf P={r['no_clf']['P']:.2f} R={r['no_clf']['R']:.2f} F1={r['no_clf']['F1']:.2f} "
              f"(w={r['no_clf']['n_walls']}) | withClf P={r['with_clf']['P']:.2f} R={r['with_clf']['R']:.2f} "
              f"F1={r['with_clf']['F1']:.2f} (w={r['with_clf']['n_walls']}, dropped={r['with_clf']['props_dropped']})")
        rows.append((name, r))
    if rows:
        import numpy as np
        for tag in ["no_clf", "with_clf"]:
            P = np.mean([r[tag]["P"] for _, r in rows]); R = np.mean([r[tag]["R"] for _, r in rows])
            F = np.mean([r[tag]["F1"] for _, r in rows])
            print(f"MEAN {tag:9s}: P={P:.3f} R={R:.3f} F1={F:.3f}")


if __name__ == "__main__":
    main()
