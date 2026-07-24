"""ConvNeXt-Tiny student wall annotation on UNLABELED maps (no GT), for a
qualitative showcase. Mirrors the DEPLOYED service inference exactly: fp32 ONNX,
single-scale 1024, reflect-pad to /32, build_graph(wall_thr=0.5). For each input
it writes a side-by-side panel [ raw map | student-annotated ] so the annotation
can be judged against the untouched image.

  .venv/bin/python pipeline/student_showcase.py --list maps.txt --out DIR
"""
import os, sys, json, base64, io, time, argparse
import numpy as np, cv2
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import onnxruntime as ort
import graph_infer

Image.MAX_IMAGE_PIXELS = None
IMEAN = np.array([0.485, 0.456, 0.406], np.float32)
ISTD = np.array([0.229, 0.224, 0.225], np.float32)
SESS = None


def load_image(path):
    """BGR uint8 from png/jpg/webp or a dd2vtt/uvtt embedded base64 image."""
    if path.lower().endswith((".dd2vtt", ".uvtt", ".df2vtt")):
        d = json.load(open(path))
        im = Image.open(io.BytesIO(base64.b64decode(d["image"]))).convert("RGB")
        return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)
    im = Image.open(path).convert("RGB")            # PIL handles webp; cv2 may not
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def predict_onnx(work):
    H, W = work.shape[:2]
    ph, pw = (32 - H % 32) % 32, (32 - W % 32) % 32
    x = (cv2.cvtColor(work, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    x = np.pad(x, ((0, ph), (0, pw), (0, 0)), mode="reflect").transpose(2, 0, 1)[None]
    out = SESS.run(None, {"image": x})[0][0]
    out = 1.0 / (1.0 + np.exp(-out))
    return out[0][:H, :W], out[1][:H, :W]


def annotate(path, wall_thr=0.5, long_edge=1024):
    img = load_image(path)
    if img is None:
        return None
    H0, W0 = img.shape[:2]
    sc = min(1.0, long_edge / max(H0, W0))
    work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
    wall, junc = predict_onnx(work)
    nodes, edges = graph_infer.build_graph(wall, junc, wall_thr=wall_thr)
    ann = work.copy()
    for a, b, t in edges:
        cv2.line(ann, tuple(map(int, nodes[a])), tuple(map(int, nodes[b])), (0, 0, 255), 2)
    # side-by-side [ raw | annotated ] with a thin separator
    gap = np.full((work.shape[0], 6, 3), 255, np.uint8)
    panel = np.hstack([work, gap, ann])
    return panel, len(edges)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="pipeline/models/wall_student_convnext_tiny.onnx")
    ap.add_argument("--list", required=True, help="text file: one image path per line")
    ap.add_argument("--out", default="corpus/results/student_showcase")
    ap.add_argument("--wall_thr", type=float, default=0.5)
    ap.add_argument("--long_edge", type=int, default=1024)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    global SESS
    so = ort.SessionOptions(); so.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 2)
    SESS = ort.InferenceSession(a.model, so, providers=["CPUExecutionProvider"])
    os.makedirs(a.out, exist_ok=True)
    paths = [ln.strip() for ln in open(a.list) if ln.strip()]
    if a.limit:
        paths = paths[:a.limit]
    print(f"model={os.path.basename(a.model)} wall_thr={a.wall_thr} n={len(paths)}", flush=True)
    for i, p in enumerate(paths):
        t0 = time.time()
        try:
            r = annotate(p, a.wall_thr, a.long_edge)
        except Exception as e:  # noqa: BLE001 — showcase must not die on one bad file
            print(f"[{i:03d}] ERR {os.path.basename(p)[:40]}: {e}", flush=True); continue
        if r is None:
            print(f"[{i:03d}] SKIP (unreadable) {p}", flush=True); continue
        panel, ne = r
        base = os.path.splitext(os.path.basename(p))[0].replace(" ", "_")
        cv2.imwrite(os.path.join(a.out, f"{i:03d}_{base}.png"), panel)
        print(f"[{i:03d}] {base[:42]:44} walls={ne:4d}  {time.time()-t0:5.1f}s", flush=True)


if __name__ == "__main__":
    main()
