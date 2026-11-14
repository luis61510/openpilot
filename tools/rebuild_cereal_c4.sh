#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAPNP_BIN="${CAPNP_BIN:-capnp}"
OUTPUT_DIR="$ROOT/openpilot/cereal/gen/cpp"

if ! command -v "$CAPNP_BIN" >/dev/null 2>&1; then
  echo "ERROR: capnp compiler not found. Activate the release-mici Python environment first." >&2
  exit 127
fi

CAPNP_VERSION="$("$CAPNP_BIN" --version 2>&1)"
if [[ "$CAPNP_VERSION" != *"1.0.1"* ]]; then
  echo "ERROR: expected Cap'n Proto 1.0.1, got: $CAPNP_VERSION" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
(
  cd "$ROOT/cereal"
  "$CAPNP_BIN" compile -I . -o "c++:$OUTPUT_DIR" custom.capnp log.capnp
)

for generated in custom.capnp.h custom.capnp.c++ log.capnp.h log.capnp.c++; do
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
