#!/bin/bash
set -euo pipefail
cd /data/home/pb/table-cleaning-ten-20261124/run-supplement
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/table-cleaning-ten-20261124/supplement-tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
exec /mnt/ceph2/wj/miniconda/envs/ms3/bin/python -B tools/variation/check_table_cleaning_pixel_adapter.py --assets /data/home/pb/table-cleaning-appearance-preview-v1/assets --output /data/home/pb/table-cleaning-ten-20261124/pixel-$SLURM_JOB_ID
