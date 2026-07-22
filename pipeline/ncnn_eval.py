#!/usr/bin/env python
"""Graph-F1 eval of the ncnn student (.param/.bin) — deployment-parity path for
the ROCm-free RX 6600 (Vulkan) / CPU target. Mirrors the scoring in
graph_eval_student.py exactly (same tolerance, same GT scaling) so numbers are
directly comparable to the ONNX/torch student.

Structured in two phases in ONE process: (1) run every ncnn forward pass, cache
the probability maps; (2) build the planar graph + score. ncnn's forward and the
graph step (which pulls in scikit-image) are kept from interleaving because on
aarch64 dev boxes ncnn's OpenMP pool segfaults if skimage's OpenMP is live during
inference; onnxruntime is imported first as an extra stabilizer. The x86 target
is unaffected. Verified on the GB10 dev box: ncnn-CPU graph-F1 = 0.722
(P0.796 R0.684) vs shipped ONNX 0.721 — deployment-equivalent.

  CPU:    .venv/bin/python pipeline/ncnn_eval.py
  Vulkan: NCNN_VULKAN=1 .venv/bin/python pipeline/ncnn_eval.py   (needs a Vulkan driver, e.g. RX 6600/RADV)
"""
import os, sys, time, argparse
try:
    import onnxruntime as _ort  # noqa: F401  (aarch64 ncnn OpenMP stabilizer; import first)
except Exception:
    pass
import numpy as np, cv2, ncnn
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uvtt import load as load_uvtt          # noqa: E402

IMEAN = np.array([0.485, 0.456, 0.406], np.float32)
ISTD = np.array([0.229, 0.224, 0.225], np.float32)
SQ = 1024   # traced input size


def make_net(param):
    net = ncnn.Net()
    net.opt.use_vulkan_compute = os.environ.get("NCNN_VULKAN", "0") == "1"
    net.opt.num_threads = int(os.environ.get("NCNN_THREADS", max(1, (os.cpu_count() or 4) - 2)))
    net.load_param(param)
    net.load_model(param.replace(".param", ".bin"))
    return net


def predict(net, work):
    """Pad the (longest-side<=1024) work image to a 1024 square, run, crop back."""
    H, W = work.shape[:2]
    x = (cv2.cvtColor(work, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    xp = np.ascontiguousarray(
        np.pad(x, ((0, SQ - H), (0, SQ - W), (0, 0)), mode="reflect").transpose(2, 0, 1).astype(np.float32))
    ex = net.create_extractor()
    ex.input("in0", ncnn.Mat(xp))
    _, out0 = ex.extract("out0")
    out = 1.0 / (1.0 + np.exp(-np.array(out0)))
    return out[0][:H, :W], out[1][:H, :W]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", default="pipeline/models/wall_student_mbv3.ncnn.param")
    ap.add_argument("--fa_list", default="corpus/fa_test_inscope.txt")
    ap.add_argument("--wall_thr", type=float, default=0.4)
    ap.add_argument("--per_map", action="store_true")
    a = ap.parse_args()
    net = make_net(a.param)
    backend = "VULKAN" if net.opt.use_vulkan_compute else f"CPU(threads={net.opt.num_threads})"
    slugs = [ln.strip() for ln in open(a.fa_list) if ln.strip()]

    # Phase 1 — ncnn forward passes only (no skimage loaded yet).
    preds, ts = [], []
    for s in slugs:
        p = os.path.join("corpus/fa", s + ".dd2vtt")
        if not os.path.exists(p):
            continue
        r = load_uvtt(p)
        if r["image"] is None or not r["walls"]:
            continue
        H0, W0 = r["image"].shape[:2]
        sc = min(1.0, SQ / max(H0, W0))
        work = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        t0 = time.time()
        wall, junc = predict(net, work)
        ts.append(time.time() - t0)
        preds.append((s, wall.astype(np.float16), junc.astype(np.float16), sc, r["ppg"],
                      np.array(r["walls"], np.float32), work.shape[:2]))

    # Phase 2 — graph build + score (skimage imported now, after all inference).
    from graph_eval_uvtt import raster, dil   # noqa: E402  (torch-free)
    import graph_infer                          # noqa: E402
    Ps, Rs, Fs = [], [], []
    for s, wall, junc, sc, ppg, walls, (RH, RW) in preds:
        nodes, edges = graph_infer.build_graph(wall.astype(np.float32), junc.astype(np.float32),
                                               wall_thr=a.wall_thr)
        pred_segs = [(nodes[i][0], nodes[i][1], nodes[j][0], nodes[j][1]) for i, j, t in edges]
        gt = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in walls], (RH, RW))
        pred = raster(pred_segs, (RH, RW))
        if pred.sum() == 0:
            P = R = Fv = 0.0
        else:
            tol = max(4, 0.4 * ppg * sc)
            P = float((pred & dil(gt, tol)).sum()) / float(pred.sum())
            R = float((gt & dil(pred, tol)).sum()) / float(gt.sum())
            Fv = 2 * P * R / (P + R + 1e-9)
        Ps.append(P); Rs.append(R); Fs.append(Fv)
        if a.per_map:
            print(f"{s:36s} NCNN  P={P:.2f} R={R:.2f} F1={Fv:.2f}", flush=True)
    if Ps:
        print(f"\nMEAN NCNN [{backend}] [{a.fa_list} (n={len(Ps)})]  "
              f"P={np.mean(Ps):.3f} R={np.mean(Rs):.3f} F1={np.mean(Fs):.3f}  "
              f"forward median={1000 * np.median(ts):.0f}ms mean={1000 * np.mean(ts):.0f}ms", flush=True)


if __name__ == "__main__":
    main()
