#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAPNP_BIN="${CAPNP_BIN:-capnp}"
CAPNPC_CXX_BIN="${CAPNPC_CXX_BIN:-capnpc-c++}"
OUTPUT_DIRS=("$ROOT/cereal/gen/cpp" "$ROOT/openpilot/cereal/gen/cpp")

for compiler in "$CAPNP_BIN" "$CAPNPC_CXX_BIN"; do
  if ! command -v "$compiler" >/dev/null 2>&1; then
    echo "ERROR: $compiler not found. Activate the release-mici Python environment first." >&2
    exit 127
  fi
done

CAPNPC_CXX_PATH="$(command -v "$CAPNPC_CXX_BIN")"
PATH="$(dirname "$CAPNPC_CXX_PATH"):$PATH"
export PATH

CAPNP_VERSION="$("$CAPNP_BIN" --version 2>&1)"
if [[ "$CAPNP_VERSION" != *"1.0.1"* ]]; then
  echo "ERROR: expected Cap'n Proto 1.0.1, got: $CAPNP_VERSION" >&2
  exit 2
fi

cd "$ROOT"

# Regenerate both the source-tree and packaged C++ schema copies.
for OUTPUT_DIR in "${OUTPUT_DIRS[@]}"; do
  mkdir -p "$OUTPUT_DIR"
  "$CAPNP_BIN" compile \
    --src-prefix=cereal \
    --src-prefix=opendbc_repo/opendbc/car \
    --import-path=opendbc_repo/opendbc/car \
    cereal/log.capnp \
    cereal/deprecated.capnp \
    cereal/custom.capnp \
    opendbc_repo/opendbc/car/car.capnp \
    -o "c++:$OUTPUT_DIR/"

  for generated in custom.capnp.h custom.capnp.c++ log.capnp.h log.capnp.c++ deprecated.capnp.h deprecated.capnp.c++ car.capnp.h car.capnp.c++; do
    if [[ ! -s "$OUTPUT_DIR/$generated" ]]; then
      echo "ERROR: expected generated file missing or empty: $OUTPUT_DIR/$generated" >&2
      exit 3
    fi
  done

  grep -q "NavAssistStateSP" "$OUTPUT_DIR/custom.capnp.h"
  grep -q "LaneTopologyStateSP" "$OUTPUT_DIR/custom.capnp.h"
  grep -q "NavLaneIntentSP" "$OUTPUT_DIR/custom.capnp.h"
  grep -q "navAssistStateSP" "$OUTPUT_DIR/log.capnp.h"
  grep -q "laneTopologyStateSP" "$OUTPUT_DIR/log.capnp.h"
  grep -q "navLaneIntentSP" "$OUTPUT_DIR/log.capnp.h"
done

# Keep the installed/package service registry in sync with cereal/services.py.
python3 "$ROOT/cereal/services.py" > "$ROOT/cereal/services.h"
cp "$ROOT/cereal/services.h" "$ROOT/openpilot/cereal/services.h"

echo "Cereal C++ artifacts and service registries regenerated with $CAPNP_VERSION."
