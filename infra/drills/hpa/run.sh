#!/usr/bin/env bash
# HPA drill (spec C10): k6 load through the Gateway while the HPA's replicas and CPU are logged every 5 s.
set -euo pipefail
source "$(dirname "$0")/../../kind/lab.env"
out=${1:-$REPO/.scratch_lab/drills/hpa}; mkdir -p "$out"
lb=$(docker ps --format '{{.Names}} {{.Ports}}' | awk '/kindccm/ && /->443/{print $1}' | head -1)
port=$(docker port "$lb" 443/tcp | head -1 | cut -d: -f2)
kubectl -n cert-manager get secret lab-ca -o jsonpath='{.data.ca\.crt}' | base64 -d > "$out/lab-ca.crt"

watch_hpa() {
  while true; do
    printf '%s %s\n' "$(date -u +%H:%M:%S)" \
      "$(kubectl -n apps get hpa podinfo -o jsonpath='{.status.currentReplicas} {.status.desiredReplicas} {.status.currentMetrics[0].resource.current.averageUtilization}')"
    sleep 5
  done
}
watch_hpa > "$out/replicas.log" & watcher=$!
trap 'kill $watcher' EXIT

echo "load starts $(date -u +%H:%M:%S)"
SSL_CERT_FILE=$out/lab-ca.crt k6 run --quiet --env PORT="$port" --summary-trend-stats "avg,p(95),p(99),max" \
  --summary-export "$out/summary.json" "$REPO/infra/drills/hpa/load.js" 2>&1 | tail -25 || true
echo "load ends $(date -u +%H:%M:%S); waiting for scale-down"
for _ in $(seq 60); do
  [[ $(kubectl -n apps get hpa podinfo -o jsonpath='{.status.currentReplicas}') == 1 ]] && break
  sleep 5
done
echo "back to 1 replica $(date -u +%H:%M:%S)"
