"""Run DINO-graph wall inference on UNLABELED map images (no GT) and save overlays.

Multi-scale variant matching the graph_eval_dino_ms benchmark protocol
(image pyramid -> fused wall/junction maps -> build_graph). RED = predicted
wall segments. Companion to heat_infer_showcase.py for qualitative showcases.

Usage:
  .venv/bin/python pipeline/dino_infer_showcase.py \
      --ckpt pipeline/models/wall_dino_fa_inscope.pt \
      --out_dir corpus/results/dino_wild_showcase img1.png img2.jpg ...
"""
import os, sys, argparse
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import graph_eval_dino as G
from graph_eval_dino_ms import ms_predict
import graph_infer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--scales", default="768,1024,1536")
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("images", nargs="+")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    G.CKPT = args.ckpt
    scales = [int(x) for x in args.scales.split(",")]

    for path in args.images:
        img = cv2.imread(path)
        if img is None:
            print(f"SKIP unreadable: {path}", flush=True)
            continue
        wall, junc, _sc = ms_predict(img, scales)
        nodes, edges = graph_infer.build_graph(wall, junc)
        segs = [(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]) for a, b, t in edges]
        H, W = wall.shape
        work = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
        ov = (work * 0.55).astype(np.uint8)
        for x0, y0, x1, y1 in segs:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        name = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(args.out_dir, f"{name}.png")
        cv2.imwrite(out, ov)
        print(f"{name}: {len(segs)} segs -> {out}", flush=True)


if __name__ == "__main__":
    main()
