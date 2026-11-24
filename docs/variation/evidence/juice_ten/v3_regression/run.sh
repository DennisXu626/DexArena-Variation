#!/bin/bash
set -uo pipefail
cd /data/home/pb/juice-ten-20261124/run-v3-regression
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/juice-ten-20261124/v3-regression-tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
OUT=/data/home/pb/juice-ten-20261124/v3-regression-$SLURM_JOB_ID
mkdir -p "$OUT"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
sha256sum tasks/juice_preparation/*.py tasks/assets/variation/juice_preparation/v1/catalog.json tools/variation/check_juice_ten_paired.py tools/variation/check_juice_short_trace_paired.py tools/variation/check_juice_critical_reset.py > "$OUT/source-sha256.txt"
status=0
for stage in OpenFridge AppleToBlender CloseFridge PlaceLid PressButton Long; do
 "$PY" -B tools/variation/check_juice_ten_paired.py "$stage" --output "$OUT/$stage" || status=1
done
"$PY" -B tools/variation/check_juice_short_trace_paired.py --output "$OUT/short_trace" || status=1
"$PY" -B tools/variation/check_juice_critical_reset.py --output "$OUT/critical" || status=1
exit "$status"
