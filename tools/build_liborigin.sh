#!/usr/bin/env bash
set -euo pipefail

src="${PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}/refs/github/liborigin"
build="${BUILD_DIR:-$src/../build/liborigin}"

mkdir -p "$build"
config_h="$build/config.h"

sed 's/${PROJECT_VERSION_MAJOR}/3/;s/${PROJECT_VERSION_MINOR}/0/;s/${PROJECT_VERSION_PATCH}/3/;s/${PROJECT_VERSION}/3.0.3/' \
    "$src/config.h.in" > "$config_h"

(
  cd "$src"
  g++ -O2 -std=c++17 -I"$build" -I"$src" -DGENERATE_CODE_FOR_LOG \
    -o "$build/opj2dat" \
    "$src/opj2dat.cpp" "$src/OriginFile.cpp" "$src/OriginParser.cpp" "$src/OriginAnyParser.cpp"
)

echo "Built liborigin oracle at $build/opj2dat"

