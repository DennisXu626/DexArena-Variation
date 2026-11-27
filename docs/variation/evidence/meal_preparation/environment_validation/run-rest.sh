#!/bin/bash
set -uo pipefail
cd /data/home/pb/meal-a4a5-final-20261120/run
export PYTHONPATH="$PWD" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export ROBOCASA_ASSET_DIR=/mnt/ceph2/DexArena/assets/task_object_meshes/MealPreparation_Assets/robocasa
export TMPDIR=/data/home/pb/meal-a4a5-final-20261120/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
status=0
for stage in bread tomato long; do
 /mnt/ceph2/wj/miniconda/envs/ms3/bin/python -B tools/variation/check_ten_environment.py meal "$stage" --output /data/home/pb/meal-a4a5-final-20261120/results-$SLURM_JOB_ID/$stage || status=1
done
exit "$status"
