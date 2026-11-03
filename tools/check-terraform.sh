#!/usr/bin/env bash
# Every Terraform check that needs no AWS account, as CI runs them:
#   tools/check-terraform.sh            fmt, validate, tflint, terraform test, Trivy
# Uses .toolchain/bin when present (the laptop), else the tools on PATH (CI).
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=$PWD/.toolchain/bin
tool() { if [[ -x "$BIN/$1" ]]; then echo "$BIN/$1"; else command -v "$1"; fi; }
TF=$(tool terraform); TFLINT=$(tool tflint); TRIVY=$(tool trivy)
ROOT=infra/aws/terraform
export TF_PLUGIN_CACHE_DIR=${TF_PLUGIN_CACHE_DIR:-$PWD/.scratch_tf/plugins}
mkdir -p "$TF_PLUGIN_CACHE_DIR"

echo "== fmt"
"$TF" fmt -check -recursive "$ROOT"

dirs=$(find "$ROOT/modules" "$ROOT/envs" -mindepth 1 -maxdepth 1 -type d | sort)
for d in $dirs; do
  echo "== $d: init, validate, test"
  "$TF" -chdir="$d" init -backend=false -input=false >/dev/null
  "$TF" -chdir="$d" validate -no-color
  "$TF" -chdir="$d" test -no-color | grep -E '^(Success|Failure)'
done

echo "== tflint"
"$TFLINT" --chdir="$ROOT" --init >/dev/null
"$TFLINT" --chdir="$ROOT" --recursive --config="$PWD/$ROOT/.tflint.hcl" --format=compact

echo "== trivy"
"$TRIVY" config --quiet --exit-code 1 --severity HIGH,CRITICAL --ignorefile "$ROOT/.trivyignore.yaml" "$ROOT"
echo "all Terraform checks passed"
