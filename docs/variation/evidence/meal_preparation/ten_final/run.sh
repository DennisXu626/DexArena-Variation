#!/bin/bash
set -euo pipefail
cd /data/home/pb/meal-ten-r3-20261120/run
export PYTHONPATH="$PWD" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export ROBOCASA_ASSET_DIR=/mnt/ceph2/DexArena/assets/task_object_meshes/MealPreparation_Assets/robocasa
export TMPDIR=/data/home/pb/meal-ten-r3-20261120/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
OUT=/data/home/pb/meal-ten-r3-20261120/results-$SLURM_JOB_ID
for mode in preview open bread tomato long; do
 "$PY" -B tools/variation/check_meal_ten.py "$mode" --output "$OUT"
done
