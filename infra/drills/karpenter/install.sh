#!/usr/bin/env bash
# Install KWOK and Karpenter's KWOK provider on kind: infra/drills/karpenter/install.sh [remove]
# Needs the Karpenter source at .scratch_lab/src/karpenter (git clone --branch v1.15.1) and Go in .toolchain/go.
set -euo pipefail
source "$(dirname "$0")/../../kind/lab.env"
SRC=$REPO/.scratch_lab/src
KVER=v1.15.1
if [[ ${1:-} == remove ]]; then
  helm -n kube-system uninstall karpenter --wait >/dev/null 2>&1 || true
  kubectl delete -f "$SRC/stage-fast.yaml" -f "$SRC/kwok.yaml" --ignore-not-found >/dev/null
  kubectl get crd -o name | grep -E 'karpenter|kwok\.x-k8s|capacitybuffers' | xargs -r kubectl delete --wait=false >/dev/null
  echo "karpenter and kwok removed"; exit 0
fi
if ! docker image inspect "karpenter-kwok:$KVER" >/dev/null 2>&1; then
  ( cd "$SRC/karpenter" && PATH=$REPO/.toolchain/go/bin:$PATH GOPATH=$REPO/.scratch_lab/go GOCACHE=$REPO/.scratch_lab/go-cache \
      CGO_ENABLED=0 GOTOOLCHAIN=local GOFLAGS=-p=2 go build -trimpath -ldflags='-s -w' -o "$SRC/karpenter-kwok" ./kwok )
  docker build -q -t "karpenter-kwok:$KVER" -f "$REPO/infra/drills/karpenter/Dockerfile" "$SRC" >/dev/null
fi
kind load docker-image --name "$CLUSTER" "karpenter-kwok:$KVER" >/dev/null
# KWOK makes the simulated nodes and pods look alive (stage-fast: ready at once).
kubectl apply -f "$SRC/kwok.yaml" >/dev/null
kubectl wait --for=condition=Established crd/stages.kwok.x-k8s.io --timeout=60s >/dev/null
kubectl apply -f "$SRC/stage-fast.yaml" >/dev/null
kubectl apply --server-side -f "$SRC/karpenter/kwok/charts/crds" >/dev/null
helm upgrade --install karpenter "$SRC/karpenter/kwok/charts" -n kube-system --skip-crds --wait --timeout 5m \
  --set controller.image.repository=karpenter-kwok --set controller.image.tag="$KVER" --set controller.image.digest="" \
  --set imagePullPolicy=Never --set replicas=1 --set settings.clusterName="$CLUSTER" \
  `# v1.15.1's KWOK chart template reads two feature gates its values.yaml does not define (empty: a panic)` \
  --set settings.featureGates.staticCapacity=false --set settings.featureGates.capacityBuffer=false \
  --set controller.resources.requests.cpu=100m --set controller.resources.requests.memory=256Mi \
  --set controller.resources.limits.memory=512Mi >/dev/null
kubectl apply -f "$REPO/infra/drills/karpenter/nodepools.yaml" >/dev/null
kubectl get nodepools
