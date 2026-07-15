#!/usr/bin/env python
"""Probe DINOv2's EMERGENT segmentation on a battlemap (no training): extract
frozen patch features, then PCA(->RGB) and KMeans clustering to see whether the
model already groups the map into meaningful regions (buildings/floor/water/...).
"""
import sys, argparse
import numpy as np, cv2, torch

DEV = "cuda"
IMEAN = np.array([0.485, 0.456, 0.406], np.float32)
ISTD = np.array([0.229, 0.224, 0.225], np.float32)


def features(img_bgr, model, long_edge=980):
    H, W = img_bgr.shape[:2]
    sc = long_edge / max(H, W)
    w = (int(W * sc) // 14) * 14; h = (int(H * sc) // 14) * 14
    r = cv2.resize(img_bgr, (w, h))
    x = (cv2.cvtColor(r, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
    xt = torch.from_numpy(x.transpose(2, 0, 1))[None].to(DEV)
    with torch.no_grad():
        f = model.forward_features(xt)["x_norm_patchtokens"][0].cpu().numpy()
    gh, gw = h // 14, w // 14
    return f.reshape(gh, gw, -1), r


def pca_rgb(feat):
    gh, gw, d = feat.shape
    X = feat.reshape(-1, d); X = X - X.mean(0)
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    p = X @ Vt[:3].T
    p = (p - p.min(0)) / (np.ptp(p, axis=0) + 1e-6)
    return (p.reshape(gh, gw, 3) * 255).astype(np.uint8)


def kmeans_map(feat, k=8):
    from sklearn.cluster import KMeans
    gh, gw, d = feat.shape
    lab = KMeans(k, n_init=4, random_state=0).fit_predict(feat.reshape(-1, d))
    rng = np.random.default_rng(1); pal = rng.integers(40, 235, (k, 3))
    return pal[lab].reshape(gh, gw, 3).astype(np.uint8)


def run(inp, out):
    model = torch.hub.load("facebookresearch/dinov2", "dinov2_vitl14").eval().to(DEV)
    print("DINOv2 ViT-L/14 loaded, dim", model.embed_dim)
    feat, disp = features(cv2.imread(inp), model)
    H, W = disp.shape[:2]
    pca = cv2.resize(pca_rgb(feat), (W, H), interpolation=cv2.INTER_NEAREST)
    km = cv2.resize(kmeans_map(feat), (W, H), interpolation=cv2.INTER_NEAREST)
    vis = np.hstack([disp, cv2.cvtColor(pca, cv2.COLOR_RGB2BGR), cv2.cvtColor(km, cv2.COLOR_RGB2BGR)])
    cv2.imwrite(out, vis)
    print("saved", out, "| left=map  mid=DINO feature PCA  right=KMeans clusters")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("-i"); ap.add_argument("-o"); a = ap.parse_args()
    run(a.i, a.o)
