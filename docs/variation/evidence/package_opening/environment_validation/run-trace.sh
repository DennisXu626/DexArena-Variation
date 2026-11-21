#!/bin/bash
set -euo pipefail
cd /data/home/pb/package-a4a5-r2-20261120/run
export PYTHONPATH="$PWD" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/package-a4a5-r2-20261120/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
exec /mnt/ceph2/wj/miniconda/envs/ms3/bin/python -B tools/variation/check_package_short_trace.py --assets /mnt/ceph2/DexArena/assets/task_object_meshes/package_opening --output /data/home/pb/package-a4a5-r2-20261120/trace-$SLURM_JOB_ID
