#!/usr/bin/env bash
# Canary drill (spec C17): infra/drills/canary/run.sh setup|good|bad|teardown
set -euo pipefail
source "$(dirname "$0")/../../kind/lab.env"
ts() { date -u +%H:%M:%S; }
status() { kubectl -n apps get rollout podinfo-rollout -o jsonpath='{.status.phase} step={.status.currentStepIndex} stable={.status.stableRS} canary={.status.currentPodHash} {.status.message}'; }
watch_rollout() {  # until Healthy or Degraded, printing each change
  local last=""
  for _ in $(seq 120); do
    s=$(status); [[ $s != "$last" ]] && { echo "$(ts) $s"; last=$s; }
    [[ $s == Healthy* && $s != *"step=0"* ]] && [[ ${1:-} == good ]] && break
    [[ $s == Degraded* ]] && break
    sleep 3
  done
  kubectl -n apps get analysisruns --sort-by=.metadata.creationTimestamp \
    -o custom-columns='RUN:.metadata.name,PHASE:.status.phase,MEASUREMENTS:.status.metricResults[0].measurements[*].value' | tail -3
}
case ${1:-} in
setup)
  "$REPO/infra/drills/optional.sh" add argo-rollouts
  kubectl apply -f "$REPO/infra/drills/canary/rollout.yaml" >/dev/null
  kubectl -n apps wait --for=jsonpath='{.status.phase}'=Healthy rollout/podinfo-rollout --timeout=300s
  echo "$(ts) $(status)" ;;
good)
  echo "$(ts) release 6.17.0"
  kubectl -n apps patch rollout podinfo-rollout --type json \
    -p '[{"op":"replace","path":"/spec/template/spec/containers/0/image","value":"ghcr.io/stefanprodan/podinfo:6.17.0"}]' >/dev/null
  watch_rollout good ;;
bad)
  echo "$(ts) release 6.17.0 with --random-error (a bad build)"
  kubectl -n apps patch rollout podinfo-rollout --type json \
    -p '[{"op":"add","path":"/spec/template/spec/containers/0/command/-","value":"--random-error"}]' >/dev/null
  watch_rollout bad
  echo "pods after the abort:"; kubectl -n apps get pods -l app.kubernetes.io/name=podinfo-rollout \
    -o custom-columns='POD:.metadata.name,HASH:.metadata.labels.rollouts-pod-template-hash,IMAGE:.spec.containers[0].image,ARGS:.spec.containers[0].command' ;;
teardown)
  kubectl delete -f "$REPO/infra/drills/canary/rollout.yaml" --ignore-not-found >/dev/null
  "$REPO/infra/drills/optional.sh" remove argo-rollouts ;;
esac
