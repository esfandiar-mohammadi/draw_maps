#!/bin/bash
# Start the wall-detection companion service (CPU, no GPU needed).
# Default model = ConvNeXt-Tiny student (graph-F1 0.765 @wall_thr 0.5).
# Usage: bash tools/run_wall_service.sh [port]
cd "$(dirname "$0")/.."
PORT="${1:-8177}"
MODEL="pipeline/models/wall_student_convnext_tiny.onnx"
if [ ! -f "$MODEL" ]; then
  echo "Model $MODEL missing — train + export the ConvNeXt-Tiny student first:"
  echo "  .venv/bin/python pipeline/train_student.py --encoder tu-convnext_tiny --pseudo corpus/distill_pl_p1 \
    --out pipeline/models/wall_student_tu_convnext_tiny.pt"
  echo "  .venv/bin/python pipeline/export_student_onnx.py \\"
  echo "      --ckpt pipeline/models/wall_student_tu_convnext_tiny.pt \\"
  echo "      --encoder tu-convnext_tiny --out $MODEL"
  echo "Or fall back to the MobileNetV3 student (0.741, ncnn/Vulkan-capable, wall_thr 0.4)."
  exit 1
fi
# wall_thr default (0.5) is baked into wall_service.py for the ConvNeXt default model.
exec .venv/bin/python pipeline/wall_service.py --model "$MODEL" --port "$PORT"
