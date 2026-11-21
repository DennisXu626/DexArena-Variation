#!/bin/bash
set -uo pipefail
cd /data/home/pb/paired-full-20261121/run
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export ROBOCASA_ASSET_DIR=/mnt/ceph2/DexArena/assets/task_object_meshes/MealPreparation_Assets/robocasa
export TMPDIR=/data/home/pb/paired-full-20261121/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
OUT=/data/home/pb/paired-full-20261121/results-$SLURM_JOB_ID
status=0
"$PY" -B tools/variation/check_package_short_trace_paired.py --assets /mnt/ceph2/DexArena/assets/task_object_meshes/package_opening --output "$OUT/package/short_trace" || status=1
exit "$status"
