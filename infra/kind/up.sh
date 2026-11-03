#!/usr/bin/env bash
# Bring up the AWS track's kind cluster: infra/kind/up.sh
# kind, a LoadBalancer controller, a local Git server, LocalStack, then Argo CD and the root app. Rerunnable.
set -euo pipefail
source "$(dirname "$0")/lab.env"
mkdir -p "$(dirname "$KUBECONFIG")"

kind get clusters 2>/dev/null | grep -qx "$CLUSTER" || kind create cluster --config "$REPO/infra/kind/cluster.yaml"

# LoadBalancer Services get an address on the kind network, as an AWS load balancer would.
docker ps --format '{{.Names}}' | grep -qx lab-cpk || docker run -d --rm --name lab-cpk --network kind \
  -v /var/run/docker.sock:/var/run/docker.sock registry.k8s.io/cloud-provider-kind/cloud-controller-manager:v0.12.0 >/dev/null

"$REPO/infra/kind/git-sync.sh"
docker image inspect lab-git-daemon:1 >/dev/null 2>&1 || \
  docker build -q -t lab-git-daemon:1 -f "$REPO/infra/kind/git-daemon.Dockerfile" "$REPO/infra/kind" >/dev/null
docker ps --format '{{.Names}}' | grep -qx lab-git || docker run -d --rm --name lab-git --network kind --user "$(id -u):$(id -g)" \
  -v "$(dirname "$GIT_MIRROR"):/git:ro" lab-git-daemon:1 >/dev/null

"$REPO/infra/kind/localstack.sh" up >/dev/null

# The cluster reaches both by Service names; the containers' addresses change per run, so they stay out of Git.
ip_of() { docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' "$1"; }
kubectl apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Namespace
metadata: {name: lab-infra}
---
apiVersion: v1
kind: Service
metadata: {name: git, namespace: lab-infra}
spec: {ports: [{name: git, port: 9418}]}
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata: {name: git, namespace: lab-infra, labels: {kubernetes.io/service-name: git}}
addressType: IPv4
ports: [{name: git, port: 9418}]
endpoints: [{addresses: ["$(ip_of lab-git)"]}]
---
apiVersion: v1
kind: Service
metadata: {name: localstack, namespace: lab-infra}
spec: {ports: [{name: edge, port: 4566}]}
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata: {name: localstack, namespace: lab-infra, labels: {kubernetes.io/service-name: localstack}}
addressType: IPv4
ports: [{name: edge, port: 4566}]
endpoints: [{addresses: ["$(ip_of lab-localstack)"]}]
YAML

helm upgrade --install argo-cd argo-cd --repo https://argoproj.github.io/argo-helm --version 10.11.6 \
  --namespace argocd --create-namespace --values "$REPO/infra/platform/values/argo-cd/kind.yaml" --wait --timeout 10m >/dev/null
kubectl apply -f "$REPO/infra/argocd/clusters/kind/root.yaml"
echo "kind cluster $CLUSTER up; Argo CD syncing infra/argocd/clusters/kind"
