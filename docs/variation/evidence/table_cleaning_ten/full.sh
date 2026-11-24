#!/bin/bash
set -uo pipefail
cd /data/home/pb/table-cleaning-ten-20261124/run-final
export PYTHONPATH="$PWD:$PWD/tools/variation" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export TMPDIR=/data/home/pb/table-cleaning-ten-20261124/full-tmp-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
OUT=/data/home/pb/table-cleaning-ten-20261124/full-$SLURM_JOB_ID
mkdir -p "$OUT"
PY=/mnt/ceph2/wj/miniconda/envs/ms3/bin/python
ASSETS=/data/home/pb/table-cleaning-appearance-preview-v1/assets
sha256sum tasks/table_cleaning/*.py tasks/assets/variation/table_cleaning/v1/catalog.json tools/variation/*table_cleaning*.py > "$OUT/source-sha256.txt"
find "$ASSETS" -type f -exec sha256sum {} + > "$OUT/asset-sha256.txt"
status=0
"$PY" -B tools/variation/check_table_cleaning_hold_cpu.py > "$OUT/hold-cpu.txt" 2>&1 || status=1
"$PY" -B tools/variation/check_table_cleaning_reset_cpu.py > "$OUT/reset-cpu.txt" 2>&1 || status=1
SDK=$($PY -c 'import mani_skill; print(next(iter(mani_skill.__path__)))')
"$PY" -B tools/variation/check_table_cleaning_state_restore_cpu.py "$PWD" "$SDK" "$OUT/state-restore-cpu.json" > "$OUT/state-restore-cpu.txt" 2>&1 || status=1
for stage in PickDebris DumpDustpan Long; do
 "$PY" -B tools/variation/check_table_cleaning_ten_paired.py "$stage" --assets "$ASSETS" --output "$OUT/$stage" || status=1
done
"$PY" -B tools/variation/check_table_cleaning_short_trace_paired.py --assets "$ASSETS" --output "$OUT/short_trace" || status=1
"$PY" -B tools/variation/check_table_cleaning_critical_reset.py --assets "$ASSETS" --output "$OUT/critical" || status=1
"$PY" -B tools/variation/render_table_cleaning_ten.py --assets "$ASSETS" --catalog tasks/assets/variation/table_cleaning/v1/catalog.json --output "$OUT/preview" || status=1
exit "$status"
