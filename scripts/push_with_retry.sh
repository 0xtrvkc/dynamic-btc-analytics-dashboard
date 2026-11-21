#!/usr/bin/env bash
# Commit staged changes (if any) and push, rebasing onto the latest main when
# another workflow pushed first. Usage: scripts/push_with_retry.sh "commit message"
set -euo pipefail
git config user.name  "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
if git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi
git commit -m "$1"
branch="${GITHUB_REF_NAME:-main}"
for attempt in 1 2 3 4 5; do
  if git pull --rebase origin "$branch" && git push origin "HEAD:$branch"; then
    exit 0
  fi
  echo "Push attempt $attempt failed; retrying in $((attempt * 10))s…"
  sleep $((attempt * 10))
done
echo "Could not push after 5 attempts." >&2
exit 1
