#!/usr/bin/env bash
# Remove everything up.sh created: infra/kind/down.sh (the Git mirror in .scratch_lab stays).
set -euo pipefail
source "$(dirname "$0")/lab.env"
kind delete cluster --name "$CLUSTER" || true
for c in lab-cpk lab-git; do docker stop "$c" >/dev/null 2>&1 || true; done
# cloud-provider-kind runs one Envoy container per LoadBalancer Service.
docker ps -q --filter "label=io.x-k8s.cloud-provider-kind.cluster=$CLUSTER" | xargs -r docker stop >/dev/null
"$REPO/infra/kind/localstack.sh" down || true
