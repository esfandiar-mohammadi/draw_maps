"""Export the distilled student (train_student.py) to ONNX for CPU/ncnn/WASM
deployment on the target hardware (DISTILL_PLAN.md P1).

- fp32 ONNX with dynamic H/W axes (fully-convolutional U-Net; inputs must be
  multiples of 32 — the service pads).
- optional INT8 static quantization, per-channel QDQ (per-tensor collapses
  segmentation quality — see DISTILL_PLAN research), calibrated on fa_tiles.
- parity check torch vs ONNX + CPU latency benchmark @1024².
"""
import os, sys, glob, argparse, time
import numpy as np, cv2, torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_seg import IMEAN, ISTD
import segmentation_models_pytorch as smp


def prep(img, size):
    img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    x = (cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    return x.transpose(2, 0, 1)[None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="pipeline/models/wall_student_mbv3.pt")
    ap.add_argument("--encoder", default="timm-mobilenetv3_large_100")
    ap.add_argument("--out", default="pipeline/models/wall_student_mbv3.onnx")
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--calib_dir", default="corpus/fa_tiles/images")
    ap.add_argument("--calib_n", type=int, default=64)
    ap.add_argument("--bench_size", type=int, default=1024)
    a = ap.parse_args()

    model = smp.Unet(a.encoder, encoder_weights=None, classes=2)
    model.load_state_dict(torch.load(a.ckpt, map_location="cpu"))
    model.eval()

    dummy = torch.randn(1, 3, 256, 256)
    torch.onnx.export(model, dummy, a.out, input_names=["image"], output_names=["logits"],
                      dynamic_axes={"image": {0: "b", 2: "h", 3: "w"},
                                    "logits": {0: "b", 2: "h", 3: "w"}},
                      opset_version=17, dynamo=False)
    print(f"exported {a.out} ({os.path.getsize(a.out)/1e6:.1f} MB)", flush=True)

    import onnxruntime as ort
    so = ort.SessionOptions(); so.intra_op_num_threads = max(1, os.cpu_count() - 2)
    sess = ort.InferenceSession(a.out, so, providers=["CPUExecutionProvider"])

    # parity torch vs onnx on a real tile
    tiles = sorted(glob.glob(f"{a.calib_dir}/*.png"))
    img = cv2.imread(tiles[0]) if tiles else np.random.randint(0, 255, (256, 256, 3), np.uint8)
    x = prep(img, 256).astype(np.float32)
    with torch.no_grad():
        yt = model(torch.from_numpy(x)).numpy()
    yo = sess.run(None, {"image": x})[0]
    diff = np.abs(yt - yo).max()
    print(f"torch/onnx parity: max|diff|={diff:.5f} {'OK' if diff < 1e-2 else 'MISMATCH!'}", flush=True)

    # dynamic-size sanity + latency at deployment size
    xb = prep(img, a.bench_size).astype(np.float32)
    sess.run(None, {"image": xb})  # warmup
    t0 = time.time(); sess.run(None, {"image": xb}); t1 = time.time()
    print(f"fp32 CPU latency @{a.bench_size}²: {t1-t0:.2f}s "
          f"({so.intra_op_num_threads} threads)", flush=True)

    if a.int8:
        from onnxruntime.quantization import (quantize_static, CalibrationDataReader,
                                              QuantFormat, QuantType)
        from onnxruntime.quantization.shape_inference import quant_pre_process

        class Reader(CalibrationDataReader):
            def __init__(self, files):
                self.it = iter(files)
            def get_next(self):
                f = next(self.it, None)
                if f is None:
                    return None
                return {"image": prep(cv2.imread(f), 256).astype(np.float32)}

        pre = a.out.replace(".onnx", "_pre.onnx")
        # symbolic shape inference chokes on the dynamic H/W axes -> onnx-only
        quant_pre_process(a.out, pre, skip_symbolic_shape=True)
        out8 = a.out.replace(".onnx", "_int8.onnx")
        quantize_static(pre, out8, Reader(tiles[:a.calib_n]),
                        quant_format=QuantFormat.QDQ, per_channel=True,
                        activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8)
        os.remove(pre)
        s8 = ort.InferenceSession(out8, so, providers=["CPUExecutionProvider"])
        y8 = s8.run(None, {"image": x})[0]
        print(f"int8 exported {out8} ({os.path.getsize(out8)/1e6:.1f} MB); "
              f"max|fp32-int8|={np.abs(yo-y8).max():.4f}", flush=True)
        s8.run(None, {"image": xb})
        t0 = time.time(); s8.run(None, {"image": xb}); t1 = time.time()
        print(f"int8 CPU latency @{a.bench_size}²: {t1-t0:.2f}s", flush=True)


if __name__ == "__main__":
    main()
