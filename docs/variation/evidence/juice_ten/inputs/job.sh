#!/bin/bash
set -euo pipefail
cd /data/home/pb/juice-ten-20261124/run
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/juice-ten-20261124/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
OUT=/data/home/pb/juice-ten-20261124/results-$SLURM_JOB_ID
"$PY" -B tools/variation/check_juice_ten_paired.py OpenFridge --output "$OUT/OpenFridge"
