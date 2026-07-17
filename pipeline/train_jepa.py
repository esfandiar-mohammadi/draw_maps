#!/usr/bin/env python
"""I-JEPA continued pretraining of the DINOv2 ViT-g backbone on the (licensed,
local-only) Drakkenheim battle maps, to adapt its features from natural photos
to the painted-map domain BEFORE supervised wall fine-tuning.

Faithful to Assran et al. 2023 (configs/in1k_vith14_ep300.yaml): multi-block
masking (1 large context, 4 target blocks), prediction in LATENT space with a
narrow ViT predictor, EMA target encoder, smooth-L1 loss. Token-dropping is
real: the context encoder only ever sees context patches (no target leakage).

Memory: only the last K backbone blocks (+ predictor) train; the frozen prefix
runs under no_grad. Target encoder is a full EMA copy (no_grad, bfloat16).
"""
import os, sys, math, random, argparse
import numpy as np, cv2, torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_seg import IMEAN, ISTD

DEV = "cuda"
CROP = 224          # 16x16 patches at patch_size 14
PATCH = 14
G = CROP // PATCH   # 16


# ----------------------------- data ---------------------------------------
class SSLTiles(torch.utils.data.Dataset):
    def __init__(self, files, length):
        self.files, self.length = files, length

    def __len__(self):
        return self.length

    def __getitem__(self, i):
        rng = random.Random(i * 2654435761 % 2**31)
        img = None
        while img is None:
            img = cv2.imread(rng.choice(self.files))
        # short-edge resize to a random target -> a ~CROP window at consistent
        # scale across mixed sources (tiny 199px donjon .. huge painted maps)
        H, W = img.shape[:2]
        target = rng.randint(CROP, CROP * 2)
        sc = target / min(H, W)
        img = cv2.resize(img, (max(CROP, round(W * sc)), max(CROP, round(H * sc))))
        H, W = img.shape[:2]
        y = rng.randint(0, H - CROP); x = rng.randint(0, W - CROP)
        crop = img[y:y + CROP, x:x + CROP]
        if rng.random() < 0.5:
            crop = crop[:, ::-1]
        xx = (cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255 - IMEAN) / ISTD
        return torch.from_numpy(np.ascontiguousarray(xx.transpose(2, 0, 1)))


# --------------------------- masking --------------------------------------
def sample_block(scale_rng, ar_rng, rng):
    scale = rng.uniform(*scale_rng)
    area = scale * G * G
    ar = rng.uniform(*ar_rng)
    h = min(G, max(1, round(math.sqrt(area / ar))))
    w = min(G, max(1, round(math.sqrt(area * ar))))
    top = rng.randint(0, G - h); left = rng.randint(0, G - w)
    return {r * G + c for r in range(top, top + h) for c in range(left, left + w)}


def sample_masks(rng, n_target=4, min_keep=10, tries=20):
    for _ in range(tries):
        targets = [sample_block((0.15, 0.2), (0.75, 1.5), rng) for _ in range(n_target)]
        tunion = set().union(*targets)
        ctx = sample_block((0.85, 1.0), (1.0, 1.0), rng) - tunion
        if len(ctx) >= min_keep and all(len(t) >= 1 for t in targets):
            return sorted(ctx), [sorted(t) for t in targets]
    # fallback: whole grid minus targets
    targets = [sample_block((0.15, 0.2), (0.75, 1.5), rng) for _ in range(n_target)]
    tunion = set().union(*targets)
    ctx = sorted(set(range(G * G)) - tunion)
    return ctx, [sorted(t) for t in targets]


# --------------------------- model ----------------------------------------
class Predictor(nn.Module):
    """Narrow ViT predictor (I-JEPA): project context -> pred_dim, add learned
    pos-embed, append mask tokens at target positions, transform, project back."""
    def __init__(self, enc_dim, pred_dim=384, depth=12, heads=6, npos=G * G):
        super().__init__()
        self.enc_to_pred = nn.Linear(enc_dim, pred_dim)
        self.pos = nn.Parameter(torch.zeros(1, npos, pred_dim))
        nn.init.trunc_normal_(self.pos, std=0.02)
        self.mask_token = nn.Parameter(torch.zeros(1, 1, pred_dim))
        nn.init.trunc_normal_(self.mask_token, std=0.02)
        layer = nn.TransformerEncoderLayer(pred_dim, heads, pred_dim * 4,
                                           activation="gelu", batch_first=True, norm_first=True)
        self.blocks = nn.TransformerEncoder(layer, depth)
        self.norm = nn.LayerNorm(pred_dim)
        self.pred_to_enc = nn.Linear(pred_dim, enc_dim)

    def forward(self, ctx_tokens, ctx_ids, target_ids_list):
        B = ctx_tokens.shape[0]
        x = self.enc_to_pred(ctx_tokens) + self.pos[:, ctx_ids]     # context repr + its pos
        preds = []
        for tids in target_ids_list:
            mt = self.mask_token + self.pos[:, tids]                # B?,|t|,d
            mt = mt.expand(B, len(tids), -1)
            seq = torch.cat([x, mt], dim=1)
            seq = self.norm(self.blocks(seq))
            preds.append(self.pred_to_enc(seq[:, x.shape[1]:]))     # only the mask-token outputs
        return preds


def embed_tokens(bb, x):
    """patch_embed + cls + interpolated pos-embed, NO transformer blocks."""
    return bb.prepare_tokens_with_masks(x)      # B, 1+N, D  (token 0 = cls)


def context_encode(bb, tok_full, ctx_ids, n_train):
    # cls (0) + context patch tokens (patch i -> token i+1)
    sel = [0] + [i + 1 for i in ctx_ids]
    t = tok_full[:, sel]
    with torch.no_grad():
        for blk in bb.blocks[:-n_train]:
            t = blk(t)
    t = t.detach()
    for blk in bb.blocks[-n_train:]:
        t = blk(t)
    t = bb.norm(t)
    return t[:, 1:]                              # drop cls -> context patch reprs


@torch.no_grad()
def target_encode(bb, x, target_ids_list):
    tok = embed_tokens(bb, x)
    for blk in bb.blocks:
        tok = blk(tok)
    tok = bb.norm(tok)
    patches = tok[:, 1:]                         # B, N, D
    return [patches[:, tids] for tids in target_ids_list]


def build_backbone():
    return torch.hub.load("facebookresearch/dinov2", "dinov2_vitg14")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssl", default="corpus/drakkenheim_split/ssl_images.txt")
    ap.add_argument("--n_train", type=int, default=6)       # trainable last-K backbone blocks
    ap.add_argument("--steps", type=int, default=6000)
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--warmup", type=int, default=300)
    ap.add_argument("--out", default="pipeline/models/dino_vitg_jepa.pt")
    ap.add_argument("--smoke", type=int, default=0)
    a = ap.parse_args()

    files = [l.strip() for l in open(a.ssl) if l.strip()]
    print(f"SSL images: {len(files)}", flush=True)
    ds = SSLTiles(files, a.bs * a.steps)
    dl = torch.utils.data.DataLoader(ds, batch_size=a.bs, num_workers=8, drop_last=True, pin_memory=True)

    ctx_bb = build_backbone().to(DEV)
    tgt_bb = build_backbone().to(DEV)
    tgt_bb.load_state_dict(ctx_bb.state_dict())
    for p in ctx_bb.parameters():
        p.requires_grad = False
    for blk in ctx_bb.blocks[-a.n_train:]:
        for p in blk.parameters():
            p.requires_grad = True
    for p in ctx_bb.norm.parameters():
        p.requires_grad = True
    for p in tgt_bb.parameters():
        p.requires_grad = False
    tgt_bb.eval()

    pred = Predictor(ctx_bb.embed_dim).to(DEV)
    train_params = [p for p in ctx_bb.parameters() if p.requires_grad] + list(pred.parameters())
    n_tr = sum(p.numel() for p in train_params)
    print(f"trainable: {n_tr/1e6:.1f}M (last-{a.n_train} blocks + norm + predictor)", flush=True)
    opt = torch.optim.AdamW(train_params, lr=a.lr, weight_decay=0.04)

    def lr_at(step):
        if step < a.warmup:
            return a.lr * step / max(1, a.warmup)
        t = (step - a.warmup) / max(1, a.steps - a.warmup)
        return 1e-6 + 0.5 * (a.lr - 1e-6) * (1 + math.cos(math.pi * t))

    mrng = random.Random(0)
    ema0, ema1 = 0.996, 1.0
    step, run = 0, 0.0
    ctx_bb.train()
    for x in dl:
        x = x.to(DEV, non_blocking=True)
        for g in opt.param_groups:
            g["lr"] = lr_at(step)
        ctx_ids, target_ids = sample_masks(mrng)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            tok_full = embed_tokens(ctx_bb, x)
            ctx_tok = context_encode(ctx_bb, tok_full, ctx_ids, a.n_train)
            targets = target_encode(tgt_bb, x, target_ids)
            preds = pred(ctx_tok, ctx_ids, target_ids)
            loss = sum(F.smooth_l1_loss(p, t) for p, t in zip(preds, targets)) / len(preds)
        opt.zero_grad()
        loss.backward()
        opt.step()
        # EMA update of target encoder
        m = ema0 + (ema1 - ema0) * min(1.0, step / a.steps)
        with torch.no_grad():
            for pe, pc in zip(tgt_bb.parameters(), ctx_bb.parameters()):
                pe.mul_(m).add_(pc.detach(), alpha=1 - m)
        run += loss.item(); step += 1
        if step % 50 == 0:
            print(f"step {step}/{a.steps}  loss {run/50:.4f}  lr {lr_at(step):.2e}", flush=True)
            run = 0.0
        if a.smoke and step >= a.smoke:
            print("SMOKE OK", flush=True); return
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    torch.save(ctx_bb.state_dict(), a.out)
    print(f"saved JEPA-adapted backbone -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
