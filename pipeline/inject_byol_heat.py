"""Inject BYOL-pretrained resnet50 weights into HEAT's backbone inside an init
checkpoint, so a HEAT fine-tune starts from the domain-adapted backbone while
keeping the corner/edge decoders. Only base_model.* keys are replaced.
"""
import sys, argparse, torch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", default="vendor/heat/checkpoints/finetune_init_battlemaps_256.pth")
    ap.add_argument("--byol", default="pipeline/models/resnet50_byol.pt")
    ap.add_argument("--out", default="vendor/heat/checkpoints/finetune_byol_init_256.pth")
    a = ap.parse_args()
    ckpt = torch.load(a.init, map_location="cpu", weights_only=False)
    byol = torch.load(a.byol, map_location="cpu")
    bb = ckpt["backbone"]
    prefix = "module.base_model." if any(k.startswith("module.base_model.") for k in bb) else "base_model."
    n = 0
    for k, v in byol.items():
        tgt = prefix + k
        if tgt in bb and bb[tgt].shape == v.shape:
            bb[tgt] = v; n += 1
    print(f"replaced {n}/{len(byol)} backbone tensors (of {len(bb)} in ckpt.backbone)")
    if n == 0:
        print("ERROR: no keys matched — check prefixes", file=sys.stderr); sys.exit(1)
    torch.save(ckpt, a.out)
    print(f"saved -> {a.out}")


if __name__ == "__main__":
    main()
