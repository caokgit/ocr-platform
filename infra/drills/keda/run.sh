#!/usr/bin/env bash
# KEDA drill (spec C11): 200 messages into the work queue; log queue depth and workers every 5 s until back to zero.
set -euo pipefail
source "$(dirname "$0")/../../kind/lab.env"
out=$REPO/.scratch_lab/drills/keda; mkdir -p "$out"
q=http://sqs.ap-southeast-1.localhost.localstack.cloud:4566/000000000000/ocr-platform-ls-work
kubectl apply -f "$REPO/infra/drills/keda/worker.yaml" >/dev/null
kubectl -n apps wait --for=condition=Ready scaledobject/sqs-worker --timeout=120s >/dev/null
depth() { docker exec lab-localstack awslocal --region ap-southeast-1 sqs get-queue-attributes --queue-url "$q" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --query 'join(`+`, [Attributes.ApproximateNumberOfMessages, Attributes.ApproximateNumberOfMessagesNotVisible])' --output text; }
echo "workers before: $(kubectl -n apps get deploy sqs-worker -o jsonpath='{.status.replicas}')"
echo "send 200 messages at $(date -u +%H:%M:%S)"
for b in $(seq 20); do
  entries=$(for i in $(seq 10); do printf '{"Id":"m%s","MessageBody":"job %s-%s"},' "$i" "$b" "$i"; done)
  docker exec lab-localstack awslocal --region ap-southeast-1 sqs send-message-batch --queue-url "$q" \
    --entries "[${entries%,}]" >/dev/null
done
for _ in $(seq 72); do
  printf '%s depth=%s workers=%s\n' "$(date -u +%H:%M:%S)" "$(depth)" \
    "$(kubectl -n apps get deploy sqs-worker -o jsonpath='{.status.replicas}')"
  sleep 5
done | tee "$out/timeline.log" | awk '{ if ($2!=d || $3!=w) print; d=$2; w=$3 }'
