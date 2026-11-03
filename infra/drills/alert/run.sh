#!/usr/bin/env bash
# Alert drill (spec C16): infra/drills/alert/run.sh inject|fix|report <since HH:MM:SS UTC>
# inject: commit the bad release into the kind overlay; fix: commit its revert; report: what the alerts and logs saw.
set -euo pipefail
source "$(dirname "$0")/../../kind/lab.env"
overlay=$REPO/infra/workloads/podinfo/kind/kustomization.yaml
sync() { "$REPO/infra/kind/git-sync.sh" >/dev/null
  kubectl -n argocd annotate application podinfo argocd.argoproj.io/refresh=normal --overwrite >/dev/null; }
case ${1:-} in
inject)
  cp "$REPO/infra/drills/alert/bad-release.yaml" "$REPO/infra/workloads/podinfo/kind/bad-release.yaml"
  cat >> "$overlay" <<'YAML'
patches:
  - target: {kind: Deployment, name: podinfo}
    path: bad-release.yaml
YAML
  git -C "$REPO" add infra/workloads/podinfo/kind
  git -C "$REPO" commit -q -m "Drill: a bad podinfo release (random errors)" -m "Spec: docs/specs/aws-track.md#acceptance"
  sync; echo "$(date -u +%H:%M:%S) bad release committed and synced ($(git -C "$REPO" rev-parse --short HEAD))"
  kubectl -n apps rollout status deploy/podinfo --timeout=180s >/dev/null
  echo "$(date -u +%H:%M:%S) bad release running" ;;
fix)
  git -C "$REPO" revert --no-edit HEAD >/dev/null
  git -C "$REPO" commit -q --amend -m "Revert the bad podinfo release" -m "Spec: docs/specs/aws-track.md#acceptance"
  sync; echo "$(date -u +%H:%M:%S) revert committed and synced ($(git -C "$REPO" rev-parse --short HEAD))"
  kubectl -n apps rollout status deploy/podinfo --timeout=180s >/dev/null
  echo "$(date -u +%H:%M:%S) good release running" ;;
report)
  since=$2
  echo "== Alertmanager notifications (alert-sink)"
  kubectl -n monitoring logs deploy/alert-sink --since-time="$(date -u -d "$since" +%Y-%m-%dT%H:%M:%SZ)" | grep -i podinfo || true
  echo "== Loki: the failing requests, per minute"
  start=$(date -u -d "$since" +%s)000000000
  kubectl -n monitoring exec deploy/alert-sink -- python -c "
import json, urllib.parse, urllib.request
q = 'sum by (status) (count_over_time({namespace=\"apps\", app=\"synthetic-traffic\"} |= \"level=error\" | logfmt [1m]))'
u = 'http://loki.monitoring.svc:3100/loki/api/v1/query_range?' + urllib.parse.urlencode({'query': q, 'start': '$start', 'step': '60'})
for s in json.load(urllib.request.urlopen(u))['data']['result']:
    print('status', s['metric'].get('status'), ' '.join(__import__('time').strftime('%H:%M', __import__('time').gmtime(int(t))) + '=' + v for t, v in s['values']))
q2 = '{namespace=\"apps\", app=\"synthetic-traffic\"} |= \"level=error\"'
u2 = 'http://loki.monitoring.svc:3100/loki/api/v1/query_range?' + urllib.parse.urlencode({'query': q2, 'start': '$start', 'limit': '3', 'direction': 'forward'})
for s in json.load(urllib.request.urlopen(u2))['data']['result']:
    for t, line in s['values'][:3]:
        print(__import__('time').strftime('%H:%M:%S', __import__('time').gmtime(int(t[:10]))), line)
" ;;
*) echo "usage: $0 inject|fix|report <since>" >&2; exit 2 ;;
esac
