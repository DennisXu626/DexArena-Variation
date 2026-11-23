#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 6 ]]; then
    printf '%s\n' 'Usage: bash build.sh COMMON_BUILD_PY HOST_WORK WHEEL_WORK PHYSX_SOURCE_TAR LINUX_RELEASE_ZIP LINUX_SO_ZIP' >&2
    exit 2
fi

recipe_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
common_recipe=$1
host_work=$2
wheel_work=$3
vendor_source=$4
host_reference=$5
gpu_archive=$6
python_bin=${PYTHON:-python3.10}
export CC=${CC:-cc}
export CXX=${CXX:-c++}
export CUDA_VISIBLE_DEVICES=

"$python_bin" -B "$recipe_dir/build_host_linux.py" prepare --work-dir "$host_work" \
    --vendor-source "$vendor_source" --host-reference "$host_reference" --gpu-archive "$gpu_archive"
"$python_bin" -B "$recipe_dir/build_host_linux.py" build --work-dir "$host_work" --cc "$CC" --cxx "$CXX"
"$python_bin" -B "$recipe_dir/build_nut_linux.py" prepare --common-recipe "$common_recipe" \
    --host-work "$host_work" --work-dir "$wheel_work"
"$python_bin" -B "$recipe_dir/build_nut_linux.py" build --common-recipe "$common_recipe" \
    --host-work "$host_work" --work-dir "$wheel_work"
