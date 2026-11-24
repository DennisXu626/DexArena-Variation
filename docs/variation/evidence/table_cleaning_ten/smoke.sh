#!/bin/bash
set -euo pipefail
cd /data/home/pb/table-cleaning-ten-20261124/run
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/table-cleaning-ten-20261124/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
exec "$PY" -B tools/variation/check_table_cleaning_ten_paired.py PickDebris --assets /data/home/pb/table-cleaning-appearance-preview-v1/assets --output /data/home/pb/table-cleaning-ten-20261124/smoke-$SLURM_JOB_ID
