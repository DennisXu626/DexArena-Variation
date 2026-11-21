#!/bin/bash
set -euo pipefail
cd /data/home/pb/minimal-diagnosis-20261121/run
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export ROBOCASA_ASSET_DIR=/mnt/ceph2/DexArena/assets/task_object_meshes/MealPreparation_Assets/robocasa
export TMPDIR=/data/home/pb/minimal-diagnosis-20261121/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
exec /mnt/ceph2/wj/miniconda/envs/ms3/bin/python -B minimal_diagnosis_history.py
