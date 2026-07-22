#!/bin/bash
# Start the wall-detection companion service (CPU, no GPU needed).
# Usage: bash tools/run_wall_service.sh [port]
cd "$(dirname "$0")/.."
PORT="${1:-8177}"
MODEL="pipeline/models/wall_student_mbv3.onnx"
if [ ! -f "$MODEL" ]; then
  echo "Model $MODEL missing — run the sprint + export first:"
  echo "  setsid bash tools/distill_sprint.sh"
  echo "  .venv/bin/python pipeline/export_student_onnx.py --ckpt pipeline/models/wall_student_mbv3.pt --out $MODEL"
  exit 1
fi
exec .venv/bin/python pipeline/wall_service.py --model "$MODEL" --port "$PORT"
