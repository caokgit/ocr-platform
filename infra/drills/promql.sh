#!/usr/bin/env bash
# Run a PromQL query or list alert states from inside the cluster: infra/drills/promql.sh '<query>' | --alerts
# (The Prometheus image has no shell tools; the alert sink's Python does the HTTP call.)
set -euo pipefail
source "$(dirname "$0")/../kind/lab.env"
kubectl -n monitoring exec deploy/alert-sink -- python -c "
import json, sys, urllib.parse, urllib.request
base = 'http://kube-prometheus-stack-prometheus.monitoring.svc:9090/api/v1/'
if sys.argv[1] == '--alerts':
    for a in json.load(urllib.request.urlopen(base + 'alerts'))['data']['alerts']:
        if a['labels'].get('alertname', '').startswith('Podinfo'):
            print(a['labels']['alertname'], a['state'], 'active since', a.get('activeAt', '')[11:19])
else:
    r = json.load(urllib.request.urlopen(base + 'query?' + urllib.parse.urlencode({'query': sys.argv[1]})))['data']['result']
    for s in r:
        print(s['metric'], s['value'][1])
" "$1"
