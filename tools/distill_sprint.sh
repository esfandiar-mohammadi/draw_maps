#!/bin/bash
# P1 distillation sprint (DISTILL_PLAN.md): waits until the Gemma llama-server
# releases the GPU, then (1) MS-teacher pseudo-labeling, (2) student training,
# (3) in-scope-32 eval single+MS. Run via:
#   setsid bash /home/spark1admin/draw_maps/tools/distill_sprint.sh
# Log: corpus/results/distill_sprint.log   (resumable: stage 1 skips done maps)
set -u
cd /home/spark1admin/draw_maps
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# drakkenheim webp maps are up to ~130MB; OpenCV default cap is 64MB
export OPENCV_IMGCODECS_WEBP_MAX_FILE_SIZE=1073741824
PY=/home/spark1admin/draw_maps/.venv/bin/python
LOG=corpus/results/distill_sprint.log

{
echo "=== distill sprint start $(date) ==="

# fp16 teacher = 4.2x throughput vs fp32, soft labels effectively identical
# (verified max|diff|=0.0065, 99.98% threshold agreement). GPU now has ~82GB
# free (Gemma shrank) so bs=32 fits with headroom; no Gemma wait-gate needed.
echo "=== stage 1a: pseudo-labeling (MS teacher, fp16, bs=32) ==="
ok=0
for try in 1 2 3 4 5 6; do
  $PY -u pipeline/distill_pseudolabel.py --out corpus/distill_pl --bs 32 --fp16 && { ok=1; break; }
  echo "pseudolabel attempt $try failed (rc=$?), retry in 90s"; sleep 90
done
[ $ok = 1 ] || { echo "PSEUDOLABEL 1a FAILED after retries $(date)"; exit 1; }

echo "=== stage 1b: pseudo-label sweep for any OOM-skipped maps ==="
$PY -u pipeline/distill_pseudolabel.py --out corpus/distill_pl --bs 16 --fp16 \
  || echo "stage 1b failed (rc=$?) — continuing with what we have"

echo "=== stage 2: student training (AMP, bs=128, 12 workers) ==="
ok=0
for try in 1 2 3 4 5 6; do
  $PY -u pipeline/train_student.py --out pipeline/models/wall_student_mbv3.pt \
      --amp --bs 128 --workers 12 && { ok=1; break; }
  echo "train attempt $try failed (rc=$?), retry in 90s"; sleep 90
done
[ $ok = 1 ] || { echo "TRAIN FAILED after retries $(date)"; exit 1; }

echo "=== stage 3: in-scope-32 eval (single 1024, then MS) $(date) ==="
$PY -u pipeline/graph_eval_student.py --scales 1024 --per_map
$PY -u pipeline/graph_eval_student.py --scales 768,1024,1536 --per_map \
    --overlay_dir corpus/results/student_overlays
echo "=== SPRINT DONE $(date) ==="
} >>"$LOG" 2>&1
