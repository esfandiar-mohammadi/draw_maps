"""Zero-shot HEAT (outdoor checkpoint) P/R/F1 vs UVTT ground truth on the
held-out hard maps — EXACTLY the same centreline metric as graph_eval_uvtt.py
(raster/dil imported from there). Map is scaled to long edge 1024, tiled into
overlapping HEAT input tiles, per-tile corners+edges are mapped back to global
coords and near-duplicate edges from tile overlaps are deduplicated."""
import os, sys, glob, argparse
import numpy as np, cv2, skimage
import scipy.ndimage as ndi
import torch
import torch.nn as nn

_PIPE = os.path.dirname(os.path.abspath(__file__))
_HEAT = os.path.join(_PIPE, "..", "vendor", "heat")
sys.path.insert(0, _PIPE)
sys.path.insert(0, _HEAT)  # before pipeline so heat's models/ package wins

from uvtt import load as load_uvtt  # noqa: E402
from graph_eval_uvtt import raster, dil  # noqa: E402
import graph_infer  # noqa: E402
from datasets.data_utils import get_pixel_features  # noqa: E402
from models.resnet import ResNetBackbone  # noqa: E402
from models.corner_models import HeatCorner  # noqa: E402
from models.edge_models import HeatEdge  # noqa: E402
from models.corner_to_edge import get_infer_edge_pairs  # noqa: E402

DEV = os.environ.get("HEAT_EVAL_DEV", "cuda")  # set HEAT_EVAL_DEV=cpu to eval off-GPU
MEAN = np.array([0.485, 0.456, 0.406]); STD = np.array([0.229, 0.224, 0.225])
HARD = ["void-town", "goblin-travel-train", "desert-tavern", "road-side-in",
        "festival-of-fools", "little-fish-academy"]


def corner_nms(preds, confs, image_size):
    data = np.zeros([image_size, image_size])
    for i in range(len(preds)):
        data[preds[i, 1], preds[i, 0]] = confs[i]
    data_max = ndi.maximum_filter(data, 5)
    maxima = (data == data_max)
    data_min = ndi.minimum_filter(data, 5)
    maxima[(data_max - data_min) <= 0] = 0
    ys, xs = np.where(maxima > 0)
    filtered = np.stack([xs, ys], axis=-1)
    return filtered, data[ys, xs]


def load_models(ckpt_path):
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    backbone = ResNetBackbone()
    strides, num_channels = backbone.strides, backbone.num_channels
    corner = HeatCorner(input_dim=128, hidden_dim=256, num_feature_levels=4,
                        backbone_strides=strides, backbone_num_channels=num_channels)
    edge = HeatEdge(input_dim=128, hidden_dim=256, num_feature_levels=4,
                    backbone_strides=strides, backbone_num_channels=num_channels)
    if DEV == "cpu":
        # checkpoints were saved from nn.DataParallel (keys prefixed "module.");
        # DataParallel forces cuda:0, so on CPU use bare modules + strip prefix.
        strip = lambda sd: {k[len("module."):] if k.startswith("module.") else k: v
                            for k, v in sd.items()}
        backbone.load_state_dict(strip(ckpt["backbone"]))
        corner.load_state_dict(strip(ckpt["corner_model"]))
        edge.load_state_dict(strip(ckpt["edge_model"]))
        # ResNetBackbone.train() returns None -> don't reassign from .eval(); mutate in place
        backbone.to(DEV).eval(); corner.to(DEV).eval(); edge.to(DEV).eval()
        corner_model, edge_model = corner, edge
    else:
        backbone = nn.DataParallel(backbone).to(DEV).eval()
        corner_model = nn.DataParallel(corner).to(DEV).eval()
        edge_model = nn.DataParallel(edge).to(DEV).eval()
        backbone.load_state_dict(ckpt["backbone"])
        corner_model.load_state_dict(ckpt["corner_model"])
        edge_model.load_state_dict(ckpt["edge_model"])
    return (backbone, corner_model, edge_model), ckpt["args"]


@torch.no_grad()
def run_tile(image_bgr, models, pixels, pixel_features, ckpt_args,
             image_size, infer_times=3, corner_thresh=0.01):
    """image_bgr: (image_size, image_size, 3) uint8 -> corners (x,y in tile
    coords), edge index pairs."""
    backbone, corner_model, edge_model = models
    img = skimage.img_as_float(image_bgr).transpose((2, 0, 1))
    img = (img - MEAN[:, None, None]) / STD[:, None, None]
    image = torch.tensor(img.astype(np.float32)).unsqueeze(0).to(DEV)

    image_feats, feat_mask, all_image_feats = backbone(image)
    pf = pixel_features.unsqueeze(0).repeat(image.shape[0], 1, 1, 1)
    c_outputs = corner_model(image_feats, feat_mask, pf, pixels, all_image_feats)
    c_np = c_outputs[0].detach().cpu().numpy()
    pos = np.where(c_np >= corner_thresh)
    pred_corners = pixels[pos]; pred_confs = c_np[pos]
    if len(pred_corners) < 2:
        return np.zeros((0, 2)), np.zeros((0, 2), int)
    pred_corners, pred_confs = corner_nms(pred_corners, pred_confs, c_outputs.shape[1])
    if len(pred_corners) < 2:
        return np.zeros((0, 2)), np.zeros((0, 2), int)
    # vendor corner_to_edge.all_combibations only covers 2..350 corners; later
    # fine-tune checkpoints can fire >350 on cluttered tiles -> KeyError. Keep
    # the 350 most confident corners (no-op for <=350).
    if len(pred_corners) > 350:
        keep = np.argsort(-pred_confs)[:350]
        pred_corners, pred_confs = pred_corners[keep], pred_confs[keep]

    pred_corners, pred_confs, edge_coords, edge_mask, edge_ids = \
        get_infer_edge_pairs(pred_corners, pred_confs)
    corner_nums = torch.tensor([len(pred_corners)]).to(image.device)
    max_candidates = torch.stack(
        [corner_nums.max() * ckpt_args.corner_to_edge_multiplier] * len(corner_nums), dim=0)

    all_pos_ids, all_edge_confs = set(), {}
    for tt in range(infer_times):
        if tt == 0:
            gt_values = torch.zeros_like(edge_mask).long(); gt_values[:, :] = 2
        s1_logits, s2_logits_hb, s2_logits_rel, selected_ids, s2_mask, s2_gt_values = \
            edge_model(image_feats, feat_mask, pf, edge_coords, edge_mask,
                       gt_values, corner_nums, max_candidates, True)
        num_filtered = s1_logits.shape[2] - selected_ids.shape[1]
        s2_np = s2_logits_hb[0].softmax(0)[1].detach().cpu().numpy().reshape(-1)
        sel = selected_ids[0].detach().cpu().numpy().reshape(-1)
        if tt != infer_times - 1:
            for pid in np.where(s2_np >= 0.9)[0]:
                aid = sel[pid]
                if gt_values[0, aid] != 2:
                    continue
                all_pos_ids.add(aid); all_edge_confs[aid] = s2_np[pid]; gt_values[0, aid] = 1
            for nid in np.where(s2_np <= 0.01)[0]:
                aid = sel[nid]
                if gt_values[0, aid] == 2:
                    gt_values[0, aid] = 0
            if (gt_values == 2).sum() <= num_filtered:
                break
        else:
            for pid in np.where(s2_np >= 0.5)[0]:
                aid = sel[pid]
                if bool(s2_mask[0][pid]) or gt_values[0, aid] != 2:
                    continue
                all_pos_ids.add(aid); all_edge_confs[aid] = s2_np[pid]
    ids = list(all_pos_ids)
    pos_edges = edge_ids[ids].cpu().numpy() if ids else np.zeros((0, 2), int)
    return pred_corners.astype(float), pos_edges


def tile_starts(dim, tile, stride):
    if dim <= tile:
        return [0]
    s = list(range(0, dim - tile + 1, stride))
    if s[-1] != dim - tile:
        s.append(dim - tile)
    return s


def predict_segments(img, models, pixels, pixel_features, ckpt_args,
                     image_size, stride=None):
    """Tile full image (already at working scale), run HEAT per tile, return
    deduplicated list of (x0,y0,x1,y1) segments in image coords."""
    stride = stride or image_size // 2
    H, W = img.shape[:2]
    segs, seen = [], set()
    for y0 in tile_starts(H, image_size, stride):
        for x0 in tile_starts(W, image_size, stride):
            crop = img[y0:y0 + image_size, x0:x0 + image_size]
            ch, cw = crop.shape[:2]
            if ch < image_size or cw < image_size:
                pad = np.zeros((image_size, image_size, 3), np.uint8)
                pad[:ch, :cw] = crop; crop = pad
            corners, edges = run_tile(crop, models, pixels, pixel_features,
                                      ckpt_args, image_size)
            for a, b in edges:
                pa = (corners[a][0] + x0, corners[a][1] + y0)
                pb = (corners[b][0] + x0, corners[b][1] + y0)
                # dedup near-identical edges from overlapping tiles (8px grid)
                ka = (round(pa[0] / 8), round(pa[1] / 8))
                kb = (round(pb[0] / 8), round(pb[1] / 8))
                key = (ka, kb) if ka <= kb else (kb, ka)
                if key in seen:
                    continue
                seen.add(key)
                segs.append((pa[0], pa[1], pb[0], pb[1]))
    return segs


def evalmap(path, models, pixels, pixel_features, ckpt_args, image_size,
            long_edge=1024, overlay_dir=None):
    r = load_uvtt(path)
    if r["image"] is None or not r["walls"]:
        return None
    H0, W0 = r["image"].shape[:2]
    sc = min(1.0, long_edge / max(H0, W0))
    work = cv2.resize(r["image"], (round(W0 * sc), round(H0 * sc)), interpolation=cv2.INTER_AREA)
    pred_segs = predict_segments(work, models, pixels, pixel_features, ckpt_args, image_size)
    # same border-frame hallucination as the seg models -> same fix (graph_infer)
    nodes = [(x0, y0) for x0, y0, _, _ in pred_segs] + [(x1, y1) for _, _, x1, y1 in pred_segs]
    edges = [(i, i + len(pred_segs), 1) for i in range(len(pred_segs))]
    kept = graph_infer.drop_border_edges(nodes, edges, work.shape)
    pred_segs = [(nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]) for a, b, _ in kept]
    gt = raster([(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]], work.shape[:2])
    pred = raster(pred_segs, work.shape[:2])
    if overlay_dir:
        ov = (work * 0.5).astype(np.uint8)  # dim base map
        gt_segs = [(x0 * sc, y0 * sc, x1 * sc, y1 * sc) for x0, y0, x1, y1 in r["walls"]]
        for x0, y0, x1, y1 in gt_segs:  # ground truth = green
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 200, 0), 2)
        for x0, y0, x1, y1 in pred_segs:  # prediction = red
            cv2.line(ov, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 255), 2)
        name = os.path.splitext(os.path.basename(path))[0]
        cv2.imwrite(os.path.join(overlay_dir, f"HEAT_eval_{name}.png"), ov)
    if pred.sum() == 0:
        return (0.0, 0.0, 0.0, 0)
    tol = max(4, 0.4 * r["ppg"] * sc)
    P = float((pred & dil(gt, tol)).sum()) / float(pred.sum())
    R = float((gt & dil(pred, tol)).sum()) / float(gt.sum())
    F = 2 * P * R / (P + R + 1e-9)
    return round(P, 3), round(R, 3), round(F, 3), len(pred_segs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="vendor/heat/checkpoints/ckpts_heat_outdoor_512/checkpoint.pth")
    ap.add_argument("--image_size", type=int, default=512)
    ap.add_argument("--overlay_dir", default="")
    ap.add_argument("--fa_test", action="store_true",
                    help="evaluate on the held-out FA maps in corpus/fa_test.txt "
                         "(instead of the 6 hard dd2vtt maps)")
    ap.add_argument("--fa_list", default="corpus/fa_test.txt",
                    help="FA slug list to evaluate when --fa_test (e.g. in-scope)")
    ap.add_argument("--per_map", action="store_true", help="print each map's P/R/F1")
    args = ap.parse_args()
    models, ckpt_args = load_models(args.ckpt)
    pixels, pixel_features = get_pixel_features(image_size=args.image_size)
    pixel_features = pixel_features.to(DEV)

    if args.fa_test:
        slugs = [ln.strip() for ln in open(args.fa_list) if ln.strip()]
        maps = [(s, os.path.join("corpus/fa", s + ".dd2vtt")) for s in slugs]
        tag = f"FA held-out ({len(maps)} maps)"
    else:
        allp = glob.glob("vendor/vtt-maps/maps/**/*.dd2vtt", recursive=True)
        maps = [(n, next((x for x in allp if os.path.basename(x) == n + ".dd2vtt"), None))
                for n in HARD]
        tag = "6 hard dd2vtt maps"

    Ps, Rs, Fs = [], [], []
    for n, p in maps:
        if not p or not os.path.exists(p):
            continue
        r = evalmap(p, models, pixels, pixel_features, ckpt_args, args.image_size,
                    overlay_dir=args.overlay_dir or None)
        if r is None:
            continue
        P, R, F, nseg = r; Ps.append(P); Rs.append(R); Fs.append(F)
        if args.per_map or not args.fa_test:
            print(f"{n:36s} HEAT  P={P:.2f} R={R:.2f} F1={F:.2f}  ({nseg} segs)", flush=True)
    if Ps:
        print(f"\nMEAN HEAT [{tag}]  P={np.mean(Ps):.3f} R={np.mean(Rs):.3f} "
              f"F1={np.mean(Fs):.3f}  (n={len(Ps)})")


if __name__ == "__main__":
    main()
