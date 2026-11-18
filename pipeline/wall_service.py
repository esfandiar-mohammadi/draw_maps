"""Local companion service: battle-map image in -> wall segments out.

The Foundry module ("Detect walls (ML)" button in auto-wall-companion) POSTs
the scene's background image here and creates Wall documents from the reply.
Runs the distilled student (ONNX, CPU by default — no ROCm/CUDA needed on the
target machine) through the same MS pyramid + build_graph as the benchmark.

  .venv/bin/python pipeline/wall_service.py --port 8177
      # default model = ConvNeXt-Tiny student (graph-F1 0.765 @wall_thr 0.5)

API (CORS: *):
  GET  /health                    -> {"status":"ok",...}
  POST /detect?scales=768,1024,1536[&seal=0|1][&format=uvtt&ppg=70]
       body = image bytes (png/jpg/webp)
       -> {"width","height","walls":[[x0,y0,x1,y1],...],"count","elapsed_s",
           "grid":{"found","size","offset_x","offset_y","size_x","size_y",
                   "coverage","confidence","reason","candidate","elapsed_s"}}
       coords in ORIGINAL image pixels (the module transforms to canvas coords).
       grid = the square grid PRINTED in the image (grid_detect.py): lines at
       offset + k*size. Apply it only when found is true; "candidate" is the
       rejected best guess (do NOT apply automatically).
"""
import os, sys, json, time, argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graph_infer
import grid_detect

# ImageNet normalization (inlined so the deployment service needs neither torch
# nor train_seg — CPU/ncnn deploy stays lightweight).
IMEAN = np.array([0.485, 0.456, 0.406], np.float32)
ISTD = np.array([0.229, 0.224, 0.225], np.float32)
SQ = 1024   # ncnn traced input size

ARGS = None


def code_id():
    """Short hash of the detection code on disk. /health reports the id the RUNNING
    process was started with; install.sh compares it with the id on disk, so an update
    (git pull) restarts a service that is healthy but still runs the old code."""
    import hashlib
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha1()
    for name in ("wall_service.py", "graph_infer.py", "grid_detect.py", "vectorize_walls.py"):
        try:
            with open(os.path.join(here, name), "rb") as f:
                h.update(name.encode() + b"\0" + f.read())
        except OSError:
            h.update(name.encode() + b"\0missing")
    return h.hexdigest()[:12]


CODE_ID = code_id()
SESS = None       # onnxruntime session (onnx backend)
NET = None        # ncnn net (ncnn backend)


def predict_onnx(work):
    H, W = work.shape[:2]
    ph, pw = (32 - H % 32) % 32, (32 - W % 32) % 32
    x = (cv2.cvtColor(work, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    x = np.pad(x, ((0, ph), (0, pw), (0, 0)), mode="reflect").transpose(2, 0, 1)[None]
    out = SESS.run(None, {"image": x})[0][0]
    out = 1.0 / (1.0 + np.exp(-out))
    return out[0][:H, :W], out[1][:H, :W]


def predict_ncnn(work):
    """ncnn path (RX 6600 Vulkan / CPU). The .param was traced at a fixed 1024
    square, so pad the (longest-side<=1024) work image up to 1024x1024 and crop."""
    import ncnn
    H, W = work.shape[:2]
    x = (cv2.cvtColor(work, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    xp = np.ascontiguousarray(
        np.pad(x, ((0, SQ - H), (0, SQ - W), (0, 0)), mode="reflect").transpose(2, 0, 1).astype(np.float32))
    ex = NET.create_extractor()
    ex.input("in0", ncnn.Mat(xp))
    _, out0 = ex.extract("out0")
    out = 1.0 / (1.0 + np.exp(-np.array(out0)))
    return out[0][:H, :W], out[1][:H, :W]


def predict(work):
    return predict_ncnn(work) if NET is not None else predict_onnx(work)


def ms_predict(img, scales, ref_long=1024):
    H0, W0 = img.shape[:2]
    rsc = min(1.0, ref_long / max(H0, W0))
    RW, RH = round(W0 * rsc), round(H0 * rsc)
    wsum = np.zeros((RH, RW), np.float32); jsum = np.zeros((RH, RW), np.float32)
    for s in scales:
        sc = min(1.0, s / max(H0, W0))
        work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        w, j = predict(work)
        wsum += cv2.resize(w, (RW, RH))
        jsum += cv2.resize(j, (RW, RH))
    return wsum / len(scales), jsum / len(scales), rsc


def detect(img, scales, seal=None):
    """seal: close gaps between wall ends (graph_infer.SEAL). None = service default.
    Trade-off measured on the 32 in-scope maps: small/medium holes -26 %/-17 %,
    precision 0.815 -> 0.809, ~40 % of the added length is not on a real wall."""
    t0 = time.time()
    seal = ARGS.seal if seal is None else seal
    wall, junc, rsc = ms_predict(img, scales)
    extra = graph_infer.SEAL if seal else {}
    nodes, edges = graph_infer.build_graph(wall, junc, wall_thr=ARGS.wall_thr, **extra)
    segs = [[round(nodes[a][0] / rsc, 1), round(nodes[a][1] / rsc, 1),
             round(nodes[b][0] / rsc, 1), round(nodes[b][1] / rsc, 1)]
            for a, b, t in edges]
    return {"width": img.shape[1], "height": img.shape[0], "walls": segs,
            "count": len(segs), "seal": bool(seal), "elapsed_s": round(time.time() - t0, 2)}


def detect_grid_safe(img):
    """Printed-grid detection on the original-resolution image; never raises."""
    t0 = time.time()
    try:
        g = grid_detect.detect_grid(img)
    except Exception as e:  # noqa: BLE001 — a grid failure must not fail wall detection
        g = {"found": False, "size": None, "offset_x": None, "offset_y": None,
             "size_x": None, "size_y": None, "coverage": None, "confidence": 0.0,
             "reason": f"grid detection failed: {e!r}", "candidate": None}
    g["elapsed_s"] = round(time.time() - t0, 2)
    return g


def to_uvtt(result, ppg):
    """Minimal UVTT (dd2vtt) skeleton for the Universal Battlemap Importer flow."""
    return {
        "format": 0.3,
        "resolution": {
            "map_origin": {"x": 0, "y": 0},
            "map_size": {"x": round(result["width"] / ppg, 2),
                         "y": round(result["height"] / ppg, 2)},
            "pixels_per_grid": ppg,
        },
        "line_of_sight": [
            [{"x": round(x0 / ppg, 4), "y": round(y0 / ppg, 4)},
             {"x": round(x1 / ppg, 4), "y": round(y1 / ppg, 4)}]
            for x0, y0, x1, y1 in result["walls"]
        ],
        "portals": [], "environment": {"baked_lighting": False, "ambient_light": "ffffffff"},
        "lights": [],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"status": "ok", "model": os.path.basename(ARGS.model),
                             "backend": ARGS.backend, "scales": ARGS.scales,
                             "wall_thr": ARGS.wall_thr, "seal": ARGS.seal,
                             "features": ["grid", "seal"], "code": CODE_ID})
        else:
            self._send(404, {"error": "unknown endpoint"})

    def do_POST(self):
        if not self.path.startswith("/detect"):
            self._send(404, {"error": "unknown endpoint"})
            return
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        scales = [int(x) for x in q.get("scales", [ARGS.scales])[0].split(",")]
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n <= 0 or n > 256 * 1024 * 1024:
                self._send(400, {"error": f"bad content-length {n}"})
                return
            data = self.rfile.read(n)
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                self._send(400, {"error": "could not decode image"})
                return
            sq = q.get("seal", [""])[0].lower()
            seal = None if sq == "" else sq in ("1", "true", "on", "yes")
            res = detect(img, scales, seal)
            res["grid"] = detect_grid_safe(img)
            if q.get("format", [""])[0] == "uvtt":
                ppg = float(q.get("ppg", ["70"])[0])
                self._send(200, to_uvtt(res, ppg))
            else:
                self._send(200, res)
            print(f"detect: {img.shape[1]}x{img.shape[0]} -> {res['count']} walls "
                  f"in {res['elapsed_s']}s", flush=True)
        except Exception as e:  # noqa: BLE001 — service must not die on one request
            import traceback; traceback.print_exc()
            self._send(500, {"error": str(e)})

    def log_message(self, *a):  # quiet default access log
        pass


def main():
    global ARGS, SESS, NET
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="pipeline/models/wall_student_convnext_tiny.onnx",
                    help="onnx backend: .onnx file. ncnn backend: the .param file. "
                         "Default = ConvNeXt-Tiny student (graph-F1 0.765 @wall_thr 0.5). "
                         "Fallback = wall_student_mbv3.onnx (0.741 @wall_thr 0.4, 26MB, "
                         "and the only ncnn/Vulkan-capable model).")
    ap.add_argument("--backend", choices=["onnx", "ncnn"], default="onnx",
                    help="onnx = CPU via onnxruntime (default). ncnn = ncnn "
                         "(add --vulkan for the RX 6600 / RADV GPU path).")
    ap.add_argument("--vulkan", action="store_true",
                    help="ncnn backend only: run on GPU via Vulkan (RX 6600/RADV, ROCm-free).")
    ap.add_argument("--port", type=int, default=8177)
    ap.add_argument("--host", default="127.0.0.1")
    # single-scale 1024 is the default: on the distilled student it matches
    # multi-scale graph-F1 (0.721 vs 0.723 in-scope-32) at ~3x the speed.
    ap.add_argument("--scales", default="1024")
    # 0.5 is the ConvNeXt-Tiny default (its best graph-F1 operating point);
    # the MobileNetV3 fallback wants 0.4. build_graph's own default stays 0.4.
    ap.add_argument("--seal", action=argparse.BooleanOptionalAction, default=True,
                    help="Close gaps between wall ends by default (graph_infer.SEAL); a request "
                         "can override with ?seal=0|1. Holes leak vision in play, so the default "
                         "is on; --no-seal gives the more conservative output.")
    ap.add_argument("--wall_thr", type=float, default=0.5,
                    help="wall-probability threshold for graph building "
                         "(0.5 = ConvNeXt-Tiny default; use 0.4 for the MobileNetV3 fallback).")
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--code_id", action="store_true",
                    help="print the id of the detection code on disk and exit (used by install.sh)")
    ARGS = ap.parse_args()
    if ARGS.code_id:
        print(CODE_ID)
        return
    if ARGS.backend == "ncnn":
        import ncnn
        NET = ncnn.Net()
        NET.opt.use_vulkan_compute = ARGS.vulkan
        NET.opt.num_threads = ARGS.threads
        NET.load_param(ARGS.model)
        NET.load_model(ARGS.model.replace(".param", ".bin"))
        dev = "Vulkan-GPU" if ARGS.vulkan else f"CPU({ARGS.threads}t)"
        print(f"wall service on http://{ARGS.host}:{ARGS.port}  backend=ncnn/{dev} "
              f"model={ARGS.model} scales={ARGS.scales}", flush=True)
    else:
        import onnxruntime as ort
        so = ort.SessionOptions(); so.intra_op_num_threads = ARGS.threads
        SESS = ort.InferenceSession(ARGS.model, so, providers=["CPUExecutionProvider"])
        print(f"wall service on http://{ARGS.host}:{ARGS.port}  backend=onnx/CPU "
              f"model={ARGS.model} scales={ARGS.scales} threads={ARGS.threads}", flush=True)
    ThreadingHTTPServer((ARGS.host, ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
