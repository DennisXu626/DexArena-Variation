#!/bin/bash
set -uo pipefail
cd /data/home/pb/table-cleaning-ten-20261124/run-recheck-v3
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/table-cleaning-ten-20261124/recheck-tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
ASSETS=/data/home/pb/table-cleaning-appearance-preview-v1/assets
OUT=/data/home/pb/table-cleaning-ten-20261124/recheck-$SLURM_JOB_ID
mkdir -p "$OUT"
status=0
"$PY" -B tools/variation/check_table_cleaning_critical_reset.py --assets "$ASSETS" --output "$OUT/critical" || status=1
"$PY" -B tools/variation/check_table_cleaning_pixel_adapter.py --assets "$ASSETS" --output "$OUT/pixel" || status=1
exit "$status"
