#!/usr/bin/env bash
# Build pipeline for the Dafny formal verification module.
#
#   1. Verifies every .dfy source and appends the solver output to
#      docs/verification_report.txt.
#   2. Compiles RiskGateway.dfy (the entry module) into a Python package under
#      risk_control/_generated/verified_risk-py/ that the engine imports.
#
# Requirements: Dafny >= 4.x on PATH (or set DAFNY=/path/to/dafny).
set -euo pipefail

DAFNY="${DAFNY:-dafny}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$PROJECT_ROOT/risk_control/_generated"
DOCS_DIR="$PROJECT_ROOT/docs"
REPORT="$DOCS_DIR/verification_report.txt"

mkdir -p "$OUT_DIR" "$DOCS_DIR"

echo "==> Verifying Dafny sources"
: > "$REPORT"
for f in "$SRC_DIR"/*.dfy; do
  name="$(basename "$f")"
  echo "  -> $name"
  "$DAFNY" verify "$f" --verification-time-limit 30 | tee -a "$REPORT"
done

echo "==> Compiling RiskGateway.dfy to Python"
"$DAFNY" translate py "$SRC_DIR/RiskGateway.dfy" \
  --output:"$OUT_DIR/verified_risk" \
  --include-runtime

echo "==> Done. Generated Python package: $OUT_DIR/verified_risk-py/"
