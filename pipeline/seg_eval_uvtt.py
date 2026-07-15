import os, sys, glob
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt
import infer_seg


def raster(segs, shape, thick=1):
    m = np.zeros(shape, np.uint8)
    for x0, y0, x1, y1 in segs:
        cv2.line(m, (int(x0), int(y0)), (int(x1), int(y1)), 255, thick)
    return m > 0


def dil(mask, tol):
    k = 2 * int(tol) + 1
    return cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0


def evalmap(path, long_edge=768):
    r = load_uvtt(path)
    if r["image"] is None or not r["walls"]:
        return None
    H0, W0 = r["image"].shape[:2]
    sc = min(1.0, long_edge / max(H0, W0))
    work = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
    prob = infer_seg.predict(work)
    # model predicts a filled wall footprint (learned thickness) -> reduce to its
    # centreline so precision/recall compare like-for-like with GT centrelines.
    from skimage.morphology import skeletonize
    binp = cv2.morphologyEx((prob > 0.5).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    pred = skeletonize(binp.astype(bool))
    gt = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]], work.shape[:2])
    tol = max(4, 0.4 * r["ppg"] * sc)
    gt_d = dil(gt, tol); pred_d = dil(pred, tol)
    P = float((pred & gt_d).sum()) / float(pred.sum() + 1e-9)
    R = float((gt & pred_d).sum()) / float(gt.sum() + 1e-9)
    F = 2 * P * R / (P + R + 1e-9)
    return round(P, 3), round(R, 3), round(F, 3)


def main():
    want = ["void-town", "goblin-travel-train", "desert-tavern", "road-side-in",
            "festival-of-fools", "little-fish-academy"]
    allp = glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True)
    picked = [p for n in want for p in allp if os.path.basename(p) == n + ".dd2vtt"]
    Ps, Rs, Fs = [], [], []
    for p in picked:
        r = evalmap(p); name = os.path.basename(p).replace(".dd2vtt", "")
        if r is None:
            continue
        P, R, F = r; Ps.append(P); Rs.append(R); Fs.append(F)
        print(f"{name:32s} SEG  P={P:.2f} R={R:.2f} F1={F:.2f}")
    if Ps:
        print(f"\nMEAN SEG  P={np.mean(Ps):.3f} R={np.mean(Rs):.3f} F1={np.mean(Fs):.3f}")
        print("(baseline earlier: CV P=0.22, SAM P=0.39, agreement P=0.52)")


if __name__ == "__main__":
    main()
