#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAPNP_BIN="${CAPNP_BIN:-capnp}"
CAPNPC_BIN="${CAPNPC_BIN:-capnpc}"
OUTPUT_DIR="$ROOT/openpilot/cereal/gen/cpp"

for compiler in "$CAPNP_BIN" "$CAPNPC_BIN"; do
  if ! command -v "$compiler" >/dev/null 2>&1; then
    echo "ERROR: $compiler not found. Activate the release-mici Python environment first." >&2
    exit 127
  fi
done

CAPNP_VERSION="$("$CAPNP_BIN" --version 2>&1)"
if [[ "$CAPNP_VERSION" != *"1.0.1"* ]]; then
  echo "ERROR: expected Cap'n Proto 1.0.1, got: $CAPNP_VERSION" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
cd "$ROOT"

# Match the upstream openpilot/cereal/SConscript source prefixes and import path.
"$CAPNPC_BIN" \
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

echo "Cereal C++ artifacts regenerated with $CAPNP_VERSION."
