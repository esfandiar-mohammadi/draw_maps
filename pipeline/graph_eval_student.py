"""graph-F1 eval of the distilled CNN student (train_student.py) vs UVTT GT.

Identical metric protocol to graph_eval_dino / graph_eval_dino_ms (ref long
edge 1024, centreline + tolerance band, build_graph unchanged) so numbers are
directly comparable to the teacher (in-scope-32 MS = 0.728). The student is a
fully-convolutional U-Net, so each pyramid scale is ONE padded forward pass —
no 252-tiling. Device via STUDENT_EVAL_DEV (default cuda; cpu works, ~6.7M).

Default map list: corpus/fa_test_inscope.txt (the in-scope-32 benchmark);
the printed MEAN is the in-scope mean directly.
"""
import os, sys, argparse
import numpy as np, cv2, torch
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt
from train_seg import IMEAN, ISTD
from graph_eval_uvtt import raster, dil
import segmentation_models_pytorch as smp
import graph_infer

DEV = os.environ.get("STUDENT_EVAL_DEV", "cuda")
_m = None
_sess = None


def model(ckpt, encoder):
    global _m
    if _m is None:
        m = smp.Unet(encoder, encoder_weights=None, classes=2).to(DEV)
        m.load_state_dict(torch.load(ckpt, map_location=DEV))
        m.eval(); _m = m
    return _m


def onnx_sess(path):
    global _sess
    if _sess is None:
        import onnxruntime as ort
        so = ort.SessionOptions(); so.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 2)
        _sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    return _sess


def predict(work, ckpt, encoder):
    """One padded full-image forward (multiple-of-32 for the U-Net).
    If ckpt ends in .onnx, run through onnxruntime (deployment parity path)."""
    H, W = work.shape[:2]
    ph, pw = (32 - H % 32) % 32, (32 - W % 32) % 32
    x = (cv2.cvtColor(work, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    if ckpt.endswith(".onnx"):
        x = np.pad(x, ((0, ph), (0, pw), (0, 0)), mode="reflect").transpose(2, 0, 1)[None]
        out = onnx_sess(ckpt).run(None, {"image": x.astype(np.float32)})[0][0]
        out = 1.0 / (1.0 + np.exp(-out))
        return out[0][:H, :W], out[1][:H, :W]
    t = torch.from_numpy(x.transpose(2, 0, 1))[None]
    t = F.pad(t, (0, pw, 0, ph), mode="reflect").to(DEV)
    with torch.no_grad():
        out = torch.sigmoid(model(ckpt, encoder)(t))[0].cpu().numpy()
    return out[0][:H, :W], out[1][:H, :W]


def ms_predict(img, scales, ckpt, encoder, ref_long=1024):
    H0, W0 = img.shape[:2]
    rsc = min(1.0, ref_long / max(H0, W0))
    RW, RH = round(W0 * rsc), round(H0 * rsc)
    wsum = np.zeros((RH, RW), np.float32); jsum = np.zeros((RH, RW), np.float32)
    for s in scales:
        sc = min(1.0, s / max(H0, W0))
        work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        w, j = predict(work, ckpt, encoder)
        wsum += cv2.resize(w, (RW, RH))
        jsum += cv2.resize(j, (RW, RH))
    return wsum / len(scales), jsum / len(scales), rsc


def evalmap(path, scales, ckpt, encoder, overlay=None, wall_thr=0.4):
    r = load_uvtt(path)
    if r["image"] is None or not r["walls"]:
        return None
    wall, junc, sc = ms_predict(r["image"], scales, ckpt, encoder)
    RH, RW = wall.shape
    nodes, edges = graph_infer.build_graph(wall, junc, wall_thr=wall_thr)
    pred_segs = [(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]) for a, b, t in edges]
    gt = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]], (RH, RW))
    pred = raster(pred_segs, (RH, RW))
    if overlay:
        work = cv2.resize(r["image"], (RW, RH), interpolation=cv2.INTER_AREA)
        ov = (work * 0.55).astype(np.uint8)
        for x0, y0, x1, y1 in [(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]]:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 255, 0), 2)
        for x0, y0, x1, y1 in pred_segs:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        cv2.imwrite(overlay, ov)
    if pred.sum() == 0:
        return (0.0, 0.0, 0.0)
    tol = max(4, 0.4 * r["ppg"] * sc)
    P = float((pred & dil(gt, tol)).sum()) / float(pred.sum())
    R = float((gt & dil(pred, tol)).sum()) / float(gt.sum())
    Fv = 2 * P * R / (P + R + 1e-9)
    return round(P, 3), round(R, 3), round(Fv, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="pipeline/models/wall_student_mbv3.pt")
    ap.add_argument("--encoder", default="timm-mobilenetv3_large_100")
    ap.add_argument("--scales", default="768,1024,1536",
                    help="pyramid scales; a single value = single-scale eval")
    ap.add_argument("--fa_list", default="corpus/fa_test_inscope.txt")
    ap.add_argument("--per_map", action="store_true")
    ap.add_argument("--overlay_dir", default="")
    ap.add_argument("--wall_thr", type=float, default=0.4,
                    help="binarization threshold in build_graph; lower = higher recall")
    a = ap.parse_args()
    scales = [int(x) for x in a.scales.split(",")]
    if a.overlay_dir:
        os.makedirs(a.overlay_dir, exist_ok=True)
    slugs = [ln.strip() for ln in open(a.fa_list) if ln.strip()]
    Ps, Rs, Fs = [], [], []
    for s in slugs:
        p = os.path.join("corpus/fa", s + ".dd2vtt")
        if not os.path.exists(p):
            print(f"MISSING {p}", flush=True)
            continue
        ov = os.path.join(a.overlay_dir, f"student_{s}.png") if a.overlay_dir else None
        r = evalmap(p, scales, a.ckpt, a.encoder, overlay=ov, wall_thr=a.wall_thr)
        if r is None:
            continue
        P, R, Fv = r; Ps.append(P); Rs.append(R); Fs.append(Fv)
        if a.per_map:
            print(f"{s:36s} STUDENT  P={P:.2f} R={R:.2f} F1={Fv:.2f}", flush=True)
    if Ps:
        print(f"\nMEAN STUDENT scales={scales} [{a.fa_list} (n={len(Ps)})]  "
              f"P={np.mean(Ps):.3f} R={np.mean(Rs):.3f} F1={np.mean(Fs):.3f}", flush=True)


if __name__ == "__main__":
    main()
