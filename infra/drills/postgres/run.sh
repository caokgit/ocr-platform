#!/usr/bin/env bash
# Database drills (spec C13 to C15) on CloudNativePG:
#   infra/drills/postgres/run.sh setup|pitr|failover [crash|graceful]|upgrade|teardown
set -euo pipefail
source "$(dirname "$0")/../../kind/lab.env"
D=$REPO/infra/drills/postgres
out=$REPO/.scratch_lab/drills/postgres; mkdir -p "$out"
ts() { date -u +%H:%M:%S; }
primary() { kubectl -n db get pod -l "cnpg.io/cluster=$1,cnpg.io/instanceRole=primary" -o jsonpath='{.items[0].metadata.name}'; }
sql() {  # cluster, query
  kubectl -n db exec "$(primary "$1")" -c postgres -- psql -qtAX -U postgres -d app -c "$2"
}
# The longest time between two successful writes, and the failures, in the writer's log since a time (UTC).
gap() {
  kubectl -n db logs deploy/writer --since-time="$(date -u -d "$1" +%Y-%m-%dT%H:%M:%SZ)" | awk '
    function s(t,  a) { split(t, a, ":"); return a[1]*3600 + a[2]*60 + a[3] }
    $2 == "ok" { if (last != "" && s($1) - s(last) > max) { max = s($1) - s(last); from = last; to = $1 } last = $1; ok++ }
    $2 == "FAIL" { fail++ }
    END { printf "writes ok=%d failed=%d; longest gap between two writes %.1f s (%s to %s)\n", ok, fail, max, from, to }'
}

case ${1:-} in
setup)
  "$REPO/infra/drills/optional.sh" add cloudnative-pg
  "$REPO/infra/drills/optional.sh" add plugin-barman-cloud
  kubectl apply -f "$D/store.yaml" -f "$D/pg16.yaml" >/dev/null
  kubectl -n db wait --for=condition=Ready cluster/pg16 --timeout=600s
  sql pg16 "CREATE TABLE IF NOT EXISTS orders (id bigserial PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(), amount numeric(10,2) NOT NULL);
            ALTER TABLE orders OWNER TO app;
            INSERT INTO orders(amount) SELECT round((random()*100)::numeric, 2) FROM generate_series(1, 200000);"
  kubectl apply -f "$D/writer.yaml" >/dev/null
  kubectl -n db rollout status deploy/writer --timeout=180s
  sleep 5; kubectl -n db logs deploy/writer --tail=3
  echo "rows: $(sql pg16 'SELECT count(*) FROM orders')"
  ;;
pitr)
  echo "$(ts) base backup"
  kubectl apply -f - >/dev/null <<YAML
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata: {name: pg16-base, namespace: db}
spec:
  cluster: {name: pg16}
  method: plugin
  pluginConfiguration: {name: barman-cloud.cloudnative-pg.io}
YAML
  kubectl -n db wait --for=jsonpath='{.status.phase}'=completed backup/pg16-base --timeout=600s
  kubectl -n db get backup pg16-base -o jsonpath='{.status.startedAt} to {.status.stoppedAt}, begin LSN {.status.beginLSN}{"\n"}'
  sleep 20
  before=$(sql pg16 "SELECT now()::timestamptz(0)")
  sql pg16 "SELECT count(*) AS rows_before_delete FROM orders WHERE id <= 1000"
  sleep 2
  echo "$(ts) the accident: DELETE FROM orders WHERE id <= 1000"
  sql pg16 "DELETE FROM orders WHERE id <= 1000; SELECT pg_switch_wal();" >/dev/null
  echo "live database now: $(sql pg16 'SELECT count(*) FROM orders WHERE id <= 1000') rows with id <= 1000; restore target $before"
  sleep 75   # archive_timeout 60 s: the WAL holding the target time reaches S3
  kubectl apply -f - >/dev/null <<YAML
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata: {name: pg16-pitr, namespace: db}
spec:
  instances: 1
  imageName: ghcr.io/cloudnative-pg/postgresql:16.13-minimal-trixie
  postgresql: {parameters: {shared_buffers: 32MB}}
  storage: {size: 1Gi}
  resources: {requests: {cpu: 100m, memory: 128Mi}, limits: {memory: 384Mi}}
  bootstrap:
    recovery:
      source: origin
      recoveryTarget: {targetTime: "$before"}
  externalClusters:
    - name: origin
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters: {barmanObjectName: lab-store, serverName: pg16}
YAML
  t0=$(date +%s)
  kubectl -n db wait --for=condition=Ready cluster/pg16-pitr --timeout=900s
  echo "$(ts) restored cluster ready after $(( $(date +%s) - t0 )) s"
  echo "restored copy: $(sql pg16-pitr 'SELECT count(*) FROM orders WHERE id <= 1000') rows with id <= 1000, $(sql pg16-pitr 'SELECT count(*) FROM orders') rows in all, newest $(sql pg16-pitr 'SELECT max(created_at)::timestamptz(0) FROM orders')"
  kubectl -n db delete cluster pg16-pitr --wait=false >/dev/null
  ;;
failover)
  # graceful: a normal pod delete (smart shutdown first); crash: the pod gone at once, as when its node dies.
  mode=${2:-crash}
  old=$(primary pg16); t=$(ts)
  echo "$t $mode: delete the primary pod $old"
  if [[ $mode == crash ]]; then
    kubectl -n db delete pod "$old" --grace-period=0 --force >/dev/null 2>&1
  else
    kubectl -n db delete pod "$old" --wait=false >/dev/null
  fi
  for _ in $(seq 120); do
    new=$(primary pg16 2>/dev/null || true)
    [[ -n $new && $new != "$old" ]] && break
    sleep 1
  done
  echo "$(ts) new primary $new"
  sleep 20
  gap "$t"
  ;;
upgrade)
  kubectl apply -f "$D/pg17.yaml" >/dev/null
  kubectl -n db wait --for=condition=Ready cluster/pg17 --timeout=900s
  echo "$(ts) pg17 ready with the schema; rows: $(sql pg17 'SELECT count(*) FROM orders')"
  for _ in $(seq 120); do
    [[ $(kubectl -n db get subscription pg17-orders -o jsonpath='{.status.applied}') == true ]] && break; sleep 2
  done
  for _ in $(seq 180); do
    a=$(sql pg16 'SELECT max(id) FROM orders'); b=$(sql pg17 'SELECT coalesce(max(id),0) FROM orders')
    (( a - b < 20 )) && break; sleep 2
  done
  echo "$(ts) caught up: pg16 max id $a, pg17 max id $b; the writer keeps writing to pg16"
  sql pg17 "SELECT 'pg17 server ' || current_setting('server_version')"
  kubectl -n db wait --for=jsonpath='{.status.instances}'=1 pooler/pg17-pooler --timeout=180s >/dev/null
  t=$(ts); echo "$t cutover: pause pg16's pooler (new queries wait, nothing is refused)"
  kubectl -n db patch pooler pg16-pooler --type merge -p '{"spec":{"pgbouncer":{"paused":true}}}' >/dev/null
  for _ in $(seq 60); do
    a=$(sql pg16 'SELECT max(id) FROM orders'); b=$(sql pg17 'SELECT coalesce(max(id),0) FROM orders')
    [[ $a == "$b" ]] && break; sleep 0.5
  done
  echo "$(ts) zero lag: both at max id $a; rows pg16 $(sql pg16 'SELECT count(*) FROM orders'), pg17 $(sql pg17 'SELECT count(*) FROM orders')"
  c16=$(sql pg16 "SELECT md5(string_agg(id || ',' || amount || ',' || created_at, ';' ORDER BY id)) FROM orders")
  c17=$(sql pg17 "SELECT md5(string_agg(id || ',' || amount || ',' || created_at, ';' ORDER BY id)) FROM orders")
  echo "checksum pg16 $c16, pg17 $c17: $([[ $c16 == "$c17" ]] && echo equal || echo DIFFERENT)"
  # Logical replication does not carry sequences: move it past the last id before writes resume.
  sql pg17 "SELECT setval('orders_id_seq', (SELECT max(id) FROM orders))" >/dev/null
  kubectl -n db patch service app-db --type merge -p '{"spec":{"selector":{"cnpg.io/poolerName":"pg17-pooler"}}}' >/dev/null
  # Held connections on pg16's pooler are released (they now fail fast and the client reconnects to pg17).
  kubectl -n db patch pooler pg16-pooler --type merge -p '{"spec":{"pgbouncer":{"paused":false}}}' >/dev/null
  echo "$(ts) app-db points at pg17's pooler"
  sleep 25
  echo "new writes land on: $(sql pg17 "SELECT 'pg17, ' || count(*) || ' rows, max id ' || max(id) FROM orders")"
  gap "$t"
  kubectl -n db delete subscription pg17-orders >/dev/null
  ;;
teardown)
  kubectl delete ns db --wait=true --timeout=300s >/dev/null || true
  "$REPO/infra/drills/optional.sh" remove plugin-barman-cloud
  "$REPO/infra/drills/optional.sh" remove cloudnative-pg
  ;;
*) echo "usage: $0 setup|pitr|failover|upgrade|teardown" >&2; exit 2 ;;
esac
