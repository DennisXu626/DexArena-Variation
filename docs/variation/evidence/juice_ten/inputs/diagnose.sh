#!/bin/bash
set -uo pipefail
cd /data/home/pb/juice-ten-20261124/run
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/juice-ten-20261124/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
OUT=/data/home/pb/juice-ten-20261124/diagnosis-$SLURM_JOB_ID
status=0
for repeat in 1 2; do
 "$PY" -B tools/variation/diagnose_juice_trace.py --native-control --output "$OUT/native-$repeat" || status=1
 "$PY" -B tools/variation/diagnose_juice_trace.py --output "$OUT/original-$repeat" || status=1
done
exit "$status"
