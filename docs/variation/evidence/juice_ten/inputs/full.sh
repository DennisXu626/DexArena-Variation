#!/bin/bash
set -uo pipefail
cd /data/home/pb/juice-ten-20261124/run
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/juice-ten-20261124/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
OUT=/data/home/pb/juice-ten-20261124/results-$SLURM_JOB_ID
status=0
for stage in AppleToBlender CloseFridge PlaceLid PressButton Long; do
 "$PY" -B tools/variation/check_juice_ten_paired.py "$stage" --output "$OUT/$stage" || status=1
done
"$PY" -B tools/variation/check_juice_short_trace_paired.py --output "$OUT/short_trace" || status=1
"$PY" -B tools/variation/check_juice_critical_reset.py --output "$OUT/critical" || status=1
"$PY" -B tools/variation/render_juice_preview.py --catalog tasks/assets/variation/juice_preparation/v1/catalog.json --output "$OUT/preview" || status=1
exit "$status"
