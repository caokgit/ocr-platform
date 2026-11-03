#!/usr/bin/env bash
# Karpenter drill (spec C12) on KWOK nodes: spot first, on-demand when the spot pool is full, a simulated spot
# reclaim drained under the PodDisruptionBudget, then consolidation back to no nodes.
set -euo pipefail
source "$(dirname "$0")/../../kind/lab.env"
out=$REPO/.scratch_lab/drills/karpenter; mkdir -p "$out"
ts() { date -u +%H:%M:%S; }
claims() {
  kubectl get nodeclaims -o custom-columns='NAME:.metadata.name,POOL:.metadata.labels.karpenter\.sh/nodepool,CAPACITY:.metadata.labels.karpenter\.sh/capacity-type,TYPE:.metadata.labels.node\.kubernetes\.io/instance-type,CPU:.status.capacity.cpu,READY:.status.conditions[?(@.type=="Ready")].status' 2>/dev/null
}
wait_ready() {  # replicas
  for _ in $(seq 120); do
    [[ $(kubectl -n apps get deploy inflate -o jsonpath='{.status.readyReplicas}') == "$1" ]] && return
    sleep 2
  done
  echo "timed out waiting for $1 ready"; return 1
}
kubectl apply -f "$REPO/infra/drills/karpenter/inflate.yaml" >/dev/null

echo "== $(ts) 6 pods of 1 CPU: the spot pool (weight 100, limit 8 CPU) takes them"
kubectl -n apps scale deploy inflate --replicas=6 >/dev/null
wait_ready 6; echo "$(ts) 6 ready"; claims

echo "== $(ts) 12 pods: spot is at its limit, the on-demand pool takes the rest"
kubectl -n apps scale deploy inflate --replicas=12 >/dev/null
wait_ready 12; echo "$(ts) 12 ready"; claims

victim=$(kubectl get nodeclaims -l karpenter.sh/capacity-type=spot -o jsonpath='{.items[0].metadata.name}')
node=$(kubectl get nodeclaim "$victim" -o jsonpath='{.status.nodeName}')
pods_on=$(kubectl -n apps get pods -l app.kubernetes.io/name=inflate --field-selector spec.nodeName="$node" --no-headers | wc -l)
echo "== $(ts) simulated spot reclaim: delete NodeClaim $victim (node $node, $pods_on inflate pods)"
( for _ in $(seq 90); do
    printf '%s ready=%s\n' "$(ts)" "$(kubectl -n apps get deploy inflate -o jsonpath='{.status.readyReplicas}')"
    sleep 1
  done ) > "$out/reclaim-ready.log" &
watcher=$!
kubectl delete nodeclaim "$victim" --wait=true --timeout=180s >/dev/null
echo "$(ts) $victim gone"
wait_ready 12; echo "$(ts) 12 ready again"
kill $watcher 2>/dev/null || true
echo "lowest ready count during the drain: $(awk -F= '{print $2}' "$out/reclaim-ready.log" | grep -v '^$' | sort -n | head -1) (PDB maxUnavailable 1, so never below 11)"
claims

echo "== $(ts) scale to 0: consolidation removes the empty nodes (consolidateAfter 1m)"
kubectl -n apps scale deploy inflate --replicas=0 >/dev/null
for _ in $(seq 90); do
  [[ -z $(kubectl get nodeclaims -o name) ]] && break
  sleep 5
done
echo "$(ts) nodeclaims left: $(kubectl get nodeclaims --no-headers 2>/dev/null | wc -l)"
kubectl get events -A --field-selector involvedObject.kind=NodeClaim --sort-by=.lastTimestamp \
  -o custom-columns=TIME:.lastTimestamp,REASON:.reason,OBJECT:.involvedObject.name,MESSAGE:.message 2>/dev/null | tail -20
