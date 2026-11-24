#!/bin/bash
set -euo pipefail
cd /data/home/pb/native-calibration-20261121/run
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export ROBOCASA_ASSET_DIR=/mnt/ceph2/DexArena/assets/task_object_meshes/MealPreparation_Assets/robocasa
export TMPDIR=/data/home/pb/native-calibration-20261121/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
for batch in 0 1; do
 for stage in open bread tomato long; do "$PY" -B calibrate_native.py meal "$stage" "$batch"; done
 for stage in open extract long; do "$PY" -B calibrate_native.py package "$stage" "$batch"; done
done
