#!/usr/bin/env bash
# Apply or remove one optional add-on for a drill:
#   infra/drills/optional.sh add|remove kyverno|keda|argo-rollouts|cloudnative-pg|plugin-barman-cloud
# Removing also deletes its CRDs: the API server keeps every CRD in memory, and the laptop is short of it.
set -euo pipefail
source "$(dirname "$0")/../kind/lab.env"
action=$1 name=$2
app=$REPO/infra/argocd/clusters/kind/optional/$name.yaml
case $action in
  add)
    kubectl apply -f "$app" >/dev/null
    kubectl -n argocd wait --for=jsonpath='{.status.health.status}'=Healthy "application/$name" --timeout=600s ;;
  remove)
    kubectl delete -f "$app" --wait=true --timeout=300s >/dev/null || true
    case $name in
      kyverno) pattern='kyverno|wgpolicyk8s' ;;
      keda) pattern='keda\.sh' ;;
      argo-rollouts) pattern='^(analysisruns|analysistemplates|clusteranalysistemplates|experiments|rollouts)\.argoproj\.io' ;;
      cloudnative-pg) pattern='postgresql\.cnpg\.io' ;;
      plugin-barman-cloud) pattern='barmancloud\.cnpg\.io' ;;
    esac
    kubectl get crd -o name | sed 's|.*/||' | grep -E "$pattern" | xargs -r kubectl delete crd --wait=false >/dev/null
    echo "$name removed" ;;
esac
