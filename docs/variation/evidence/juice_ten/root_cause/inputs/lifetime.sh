#!/bin/bash
set -uo pipefail
cd /data/home/pb/juice-ten-20261124/run
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/juice-ten-20261124/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
OUT=/data/home/pb/juice-ten-20261124/lifetime-$SLURM_JOB_ID
"$PY" -B tools/variation/diagnose_lifetime.py --output "$OUT/old"
"$PY" -B tools/variation/diagnose_lifetime.py --release --output "$OUT/released"
