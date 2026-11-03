#!/usr/bin/env bash
# Start or stop LocalStack for the AWS track: infra/kind/localstack.sh up|down|status
# Pinned to 4.14.0, the last community image that runs without a sign-in token.
set -euo pipefail
NAME=lab-localstack
IMAGE=localstack/localstack:4.14.0
case "${1:-status}" in
  up)
    if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
      docker run -d --rm --name "$NAME" -p 127.0.0.1:4566:4566 \
        -e SERVICES=ec2,events,iam,kms,logs,s3,s3control,secretsmanager,sqs,sts "$IMAGE" >/dev/null
    fi
    # kind's nodes reach LocalStack by its address on the kind network.
    if docker network inspect kind >/dev/null 2>&1; then
      docker network connect kind "$NAME" 2>/dev/null || true
    fi
    for _ in $(seq 60); do
      curl -sf localhost:4566/_localstack/health >/dev/null && break
      sleep 1
    done
    curl -s localhost:4566/_localstack/health | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]; print(" ".join(f"{k}={v}" for k,v in sorted(s.items()) if v!="disabled"))'
    ;;
  down) docker stop "$NAME" >/dev/null && echo stopped ;;
  status) docker ps --filter "name=$NAME" --format '{{.Names}} {{.Status}}' ;;
  *) echo "usage: $0 up|down|status" >&2; exit 2 ;;
esac
