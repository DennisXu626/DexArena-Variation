#!/bin/bash
set -euo pipefail
ROOT=/data/home/pb/pr31-r1-fix-20261123
cd "$ROOT/source"
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export MS_ASSET_DIR=/mnt/ceph2/wym/ms_asset
export TMPDIR="$ROOT/tmp-$SLURM_JOB_ID"
mkdir -p "$TMPDIR"
exec /mnt/ceph2/wj/miniconda/envs/ms3/bin/python -B tools/variation/render_package_ten.py --assets /mnt/ceph2/DexArena/assets/task_object_meshes/package_opening --output "$ROOT/preview-$SLURM_JOB_ID"
