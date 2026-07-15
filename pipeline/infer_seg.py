#!/usr/bin/env python
"""Run the fine-tuned wall segmentation model on an image -> wall probability."""
import os, sys
import numpy as np, cv2, torch
import segmentation_models_pytorch as smp

DEV = "cuda"
IMEAN = np.array([0.485, 0.456, 0.406], np.float32)
ISTD = np.array([0.229, 0.224, 0.225], np.float32)
_model = None


def get_model():
    global _model
    if _model is None:
        m = smp.Unet(encoder_name="resnet34", encoder_weights=None, classes=1).to(DEV)
        m.load_state_dict(torch.load("pipeline/models/wall_seg_unet.pt", map_location=DEV))
        m.eval(); _model = m
    return _model


def predict(img_bgr, tile=256):
    """Predict wall probability at the image's resolution by tiling."""
    m = get_model()
    H, W = img_bgr.shape[:2]
    # scale so a tile ~ covers a donjon-like extent (train imgs ~256 for whole dungeon);
    # here we resize whole image to a grid of 256 tiles at 1x (no extreme zoom)
    prob = np.zeros((H, W), np.float32); cnt = np.zeros((H, W), np.float32)
    step = tile
    xs = list(range(0, max(1, W - tile) + 1, step)) or [0]
    ys = list(range(0, max(1, H - tile) + 1, step)) or [0]
    if xs[-1] != W - tile and W > tile: xs.append(W - tile)
    if ys[-1] != H - tile and H > tile: ys.append(H - tile)
    batch, coords = [], []
    for y in ys:
        for x in xs:
            crop = img_bgr[y:y + tile, x:x + tile]
            ch, cw = crop.shape[:2]
            c = cv2.resize(crop, (tile, tile))
            xx = (cv2.cvtColor(c, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - IMEAN) / ISTD
            batch.append(xx.transpose(2, 0, 1)); coords.append((y, x, ch, cw))
    with torch.no_grad():
        for i in range(0, len(batch), 16):
            b = torch.from_numpy(np.stack(batch[i:i + 16])).to(DEV)
            pr = torch.sigmoid(get_model()(b)).cpu().numpy()[:, 0]
            for j, p in enumerate(pr):
                y, x, ch, cw = coords[i + j]
                prob[y:y + ch, x:x + cw] += cv2.resize(p, (tile, tile))[:ch, :cw]
                cnt[y:y + ch, x:x + cw] += 1
    return prob / np.maximum(cnt, 1)


def overlay(img, prob, thr=0.5):
    ov = img.copy()
    heat = (prob * 255).astype(np.uint8)
    ov[prob > thr] = (0, 0, 255)
    return ov, heat


if __name__ == "__main__":
    import glob
    from PIL import Image
    S = "/tmp/claude-1000/-home-spark1admin-draw-maps/cf6b135d-83e9-476c-b084-95aff54a5c4c/scratchpad"
    for name, path, scale in [("map01_forest", "corpus/maps/map01_3hrm78ikqtif1.png", 0.5),
                              ("map02_town", "corpus/maps/map02_5hsf6yxnkvkf1.jpeg", 0.35),
                              ("map07_ravine", "corpus/maps/map07_r9p4h2zsm4wg1.jpeg", 0.4)]:
        img = cv2.imread(path)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        prob = predict(img)
        ov, heat = overlay(img, prob)
        vis = np.hstack([img, cv2.applyColorMap(heat, cv2.COLORMAP_JET), ov])
        im = Image.fromarray(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)); im.thumbnail((1400, 700))
        im.save(f"{S}/seg_{name}.png"); print(name, "prob mean", round(float(prob.mean()), 3))
