#!/bin/bash
set -euo pipefail
root="${RUN_ROOT:?set RUN_ROOT to the private deployment}"
cd "$root/run"
export PYTHONPATH="$PWD:$root" TMPDIR="$root/tmp-$SLURM_JOB_ID" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
mkdir -p "$TMPDIR"
exec /mnt/ceph2/wj/miniconda/envs/ms3/bin/python -B "$root/parallel/$1.py" "${@:2}"
