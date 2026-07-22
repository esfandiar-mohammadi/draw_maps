"""Run HEAT wall inference on UNLABELED map images (no GT) and save overlays.

Reuses load_models/predict_segments from heat_eval_uvtt; resizes each map to
long edge 1024 (same as eval), drops border-hallucination edges, draws the
predicted wall segments in RED on the dimmed map. For qualitative showcases
on maps outside the labeled corpus (H2: look at them).

Usage:
  HEAT_EVAL_DEV=cpu .venv/bin/python pipeline/heat_infer_showcase.py \
      --ckpt vendor/heat/checkpoints/ckpts_heat_fa_inscope/checkpoint_ep80.pth \
      --image_size 256 --out_dir corpus/results/heat_wild_showcase img1.png img2.jpg ...
"""
import os, sys, argparse
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(__file__))
import graph_infer
from heat_eval_uvtt import load_models, predict_segments, DEV  # noqa: F401
from datasets.data_utils import get_pixel_features  # noqa: E402 (vendor/heat path set by heat_eval_uvtt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--image_size", type=int, default=256)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--long_edge", type=int, default=1024)
    ap.add_argument("images", nargs="+")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    models, ckpt_args = load_models(args.ckpt)
    pixels, pixel_features = get_pixel_features(image_size=args.image_size)
    pixel_features = pixel_features.to(DEV)

    for path in args.images:
        img = cv2.imread(path)
        if img is None:
            print(f"SKIP unreadable: {path}", flush=True)
            continue
        H0, W0 = img.shape[:2]
        sc = min(1.0, args.long_edge / max(H0, W0))
        work = cv2.resize(img, (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
        segs = predict_segments(work, models, pixels, pixel_features, ckpt_args, args.image_size)
        # same border-frame fix as evalmap
        nodes = [(x0, y0) for x0, y0, _, _ in segs] + [(x1, y1) for _, _, x1, y1 in segs]
        edges = [(i, i + len(segs), 1) for i in range(len(segs))]
        kept = graph_infer.drop_border_edges(nodes, edges, work.shape)
        segs = [(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]) for a, b, _ in kept]
        ov = (work * 0.55).astype(np.uint8)
        for x0, y0, x1, y1 in segs:
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        name = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(args.out_dir, f"{name}.png")
        cv2.imwrite(out, ov)
        print(f"{name}: {len(segs)} segs -> {out}", flush=True)


if __name__ == "__main__":
    main()
