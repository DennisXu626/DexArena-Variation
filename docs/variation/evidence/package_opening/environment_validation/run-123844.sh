#!/bin/bash
set -uo pipefail
cd /data/home/pb/package-a4a5-final-20261120/run
export PYTHONPATH="$PWD" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/package-a4a5-final-20261120/tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
status=0
for stage in open extract long; do
 /mnt/ceph2/wj/miniconda/envs/ms3/bin/python -B tools/variation/check_ten_environment.py package "$stage" --assets /mnt/ceph2/DexArena/assets/task_object_meshes/package_opening --output /data/home/pb/package-a4a5-final-20261120/results-$SLURM_JOB_ID/$stage || status=1
done
exit "$status"
