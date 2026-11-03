#!/usr/bin/env bash
# Render every cluster's manifests and Helm add-ons, then validate them with kubeconform (spec C5):
#   tools/check-manifests.sh [kind|eks ...]     (default: eks kind)
# Kubernetes schemas from kubeconform's default source; CRD schemas from the CRDs-catalog. A kind with no schema in
# either is counted and listed, not silently passed.
set -euo pipefail
cd "$(dirname "$0")/.."
BIN=$PWD/.toolchain/bin
tool() { if [[ -x "$BIN/$1" ]]; then echo "$BIN/$1"; else command -v "$1"; fi; }
KUBECTL=$(tool kubectl); HELM=$(tool helm); KUBECONFORM=$(tool kubeconform)
export HELM_CACHE_HOME=$PWD/.scratch_helm/cache HELM_CONFIG_HOME=$PWD/.scratch_helm/config HELM_DATA_HOME=$PWD/.scratch_helm/data
out=$(mktemp -d); trap 'rm -rf "$out"' EXIT
K8S_VERSION=1.35.0
CRDS='https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

render() {  # cluster
  local c=$1 d=$out/$1; mkdir -p "$d"
  "$KUBECTL" kustomize "infra/platform/manifests/$c" > "$d/platform-config.yaml"
  "$KUBECTL" kustomize "infra/workloads/podinfo/$c" > "$d/podinfo.yaml"
  cp infra/argocd/clusters/$c/root.yaml infra/argocd/clusters/$c/apps/*.yaml "$d/"
  # Each add-on in the cluster's ApplicationSet, rendered with common.yaml and the cluster's values file.
  python3 - "infra/argocd/clusters/$c/apps/platform.yaml" <<'PY' > "$d/addons.txt"
import re, sys
for m in re.finditer(r"\{name: ([^,]+), namespace: ([^,]+), repoURL: ([^,]+), chart: ([^,]+), version: ([^,]+),", open(sys.argv[1]).read()):
    print(*m.groups())
PY
  while read -r name ns repo chart version; do
    case $repo in http*) src=(--repo "$repo" "$chart") ;; *) src=("oci://$repo/$chart") ;; esac
    vals=()
    for f in common "$c"; do [[ -f infra/platform/values/$name/$f.yaml ]] && vals+=(-f "infra/platform/values/$name/$f.yaml"); done
    "$HELM" template "$name" "${src[@]}" --version "$version" -n "$ns" --include-crds --kube-version "$K8S_VERSION" \
      "${vals[@]}" > "$d/chart-$name.yaml"
    echo "rendered $c/$name $version"
  done < "$d/addons.txt"
}

for c in "${@:-eks kind}"; do
  for cl in $c; do
    render "$cl"
    echo "== kubeconform $cl"
    "$KUBECONFORM" -strict -summary -output text -kubernetes-version "$K8S_VERSION" \
      -schema-location default -schema-location "$CRDS" -ignore-missing-schemas "$out/$cl"/*.yaml \
      | tee "$out/$cl.result" | grep -vE '^\S+ - (Skipped|skipped)' || true
    grep -q 'Invalid: 0, Errors: 0' "$out/$cl.result" || { echo "kubeconform found problems in $cl"; exit 1; }
    "$KUBECONFORM" -summary -output json -kubernetes-version "$K8S_VERSION" -schema-location default \
      -schema-location "$CRDS" -ignore-missing-schemas -verbose "$out/$cl"/*.yaml 2>/dev/null | python3 -c "
import json, sys, collections
r = json.load(sys.stdin)['resources']
skipped = collections.Counter(x['kind'] for x in r if x['status'] == 'statusSkipped')
print('no schema found for:', ', '.join(f'{k} x{n}' for k, n in sorted(skipped.items())) or 'none')"
  done
done
