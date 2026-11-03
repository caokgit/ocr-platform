#!/usr/bin/env bash
# Publish the repo's current commit to the local Git server that Argo CD on kind reads (branch main).
set -euo pipefail
source "$(dirname "$0")/lab.env"
[[ -d $GIT_MIRROR ]] || git init -q --bare "$GIT_MIRROR"
git -C "$REPO" push -q --force "$GIT_MIRROR" HEAD:refs/heads/main
echo "kind mirror at $(git -C "$GIT_MIRROR" rev-parse --short main)"
