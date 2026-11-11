#!/usr/bin/env bash
# Does a change touch a path this CI job checks? (docs/specs/aws-track.md#decisions, decision 21)
#   tools/ci-paths.sh <terraform|manifests> [<git range>]   prints one line ending in run=true or run=false
# In a pull_request run, HEAD is GitHub's test merge commit, so HEAD^1..HEAD (the default) is what the pull request brings
# in; a push run passes <before>..<after>, which needs the full history (fetch-depth 0): a push may carry many commits.
# In Actions the answer also goes to $GITHUB_OUTPUT for the job's later steps.
# Fails closed: if the change cannot be read, the script exits non-zero and the job fails; it never skips by mistake.
set -euo pipefail
job=${1:?usage: tools/ci-paths.sh <terraform|manifests> [<git range>]}
range=${2:-HEAD^1..HEAD}
always='^(\.github/workflows/ci\.yml|tools/ci-paths\.sh)$'   # the workflow and this script: every job runs
case $job in
  terraform) paths='^(infra/aws/terraform/|tools/check-terraform\.sh$)' ;;
  manifests) paths='^(infra/platform/|infra/workloads/|infra/argocd/clusters/|tools/check-manifests\.sh$)' ;;
  *) echo "ci-paths: unknown job '$job'" >&2; exit 2 ;;
esac
files=$(git diff --name-only "$range")
hits=$(grep -E -e "$always" -e "$paths" <<<"$files" || true)
if [[ -n $hits ]]; then run=true; else run=false; fi
echo "$job: $(grep -c . <<<"$files" || true) files changed, $(grep -c . <<<"$hits" || true) checked by this job: run=$run"
[[ -z ${GITHUB_OUTPUT:-} ]] || echo "run=$run" >> "$GITHUB_OUTPUT"
