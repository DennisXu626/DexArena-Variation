#!/bin/bash
set -uo pipefail
ROOT=/data/home/pb/pr31-r1-fix-20261123
cd "$ROOT/source"
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export MS_ASSET_DIR=/mnt/ceph2/wym/ms_asset
export ROBOCASA_ASSET_DIR=/mnt/ceph2/DexArena/assets/task_object_meshes/MealPreparation_Assets/robocasa
export TMPDIR="$ROOT/tmp-$SLURM_JOB_ID"
mkdir -p "$TMPDIR"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
OUT="$ROOT/results-$SLURM_JOB_ID"
mkdir -p "$OUT"
env | sort > "$OUT/job-environment.txt"
status=0
"$PY" -B -m unittest discover -s tests -p test_package_control_targets.py -v > "$OUT/cpu-tests.log" 2>&1 || status=1
for stage in open extract long; do
  "$PY" -B tools/variation/check_ten_environment_paired.py package "$stage" --assets /mnt/ceph2/DexArena/assets/task_object_meshes/package_opening --output "$OUT/$stage" > "$OUT/$stage.log" 2>&1 || status=1
done
exit "$status"
