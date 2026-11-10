#!/usr/bin/env bash
# Ingest pi sessions into the local pika, rebuild the static site, commit, and push to GitHub.
#
#   scripts/publish.sh --project pi-trials ~/.pi/agent/sessions/--root-pi-runs-trial-01--/*.jsonl
#   scripts/publish.sh                      # just rebuild + push what pika already has
#
# Render redeploys on push. Secrets: GitHub PAT in ~/.config/trajectory-render/github_pat,
# extra literals to mask in ~/.config/trajectory-render/redact.txt (both chmod 600, never committed).
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT=""
if [[ "${1:-}" == "--project" ]]; then PROJECT="$2"; shift 2; fi

scripts/pika_serve.sh
if [[ $# -gt 0 ]]; then
  [[ -n "$PROJECT" ]] || { echo "--project NAME is required when ingesting files" >&2; exit 2; }
  python3 -I scripts/pika_ingest.py --token-file /root/pika-data/ingest.token --project "$PROJECT" --publish "$@"
fi
# PUBLISH_ALL=0 publishes only projects already marked published in pika (e.g. after unpublishing someone else's
# test sessions); the default keeps the original behaviour of publishing every project.
if [[ "${PUBLISH_ALL:-1}" == 1 ]]; then python3 -I scripts/pika_publish_all.py; fi
scripts/build_site.sh

git add -A
if ! git diff --cached --quiet; then
  git -c user.name="trajectory-bot" -c user.email="trajectory-bot@users.noreply.github.com" \
    commit -q -m "Publish trajectories ($(date -u +%Y-%m-%dT%H:%MZ))"
fi
TOKEN="$(cat ~/.config/trajectory-render/github_pat)"
AUTH="$(printf "x-access-token:%s" "$TOKEN" | base64 -w0)"
# The global git proxy on this box is stale; use the one from the environment for GitHub.
PROXY=(); if [[ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]]; then P="${HTTPS_PROXY:-$https_proxy}"; PROXY=(-c http.proxy="$P" -c https.proxy="$P"); fi
for i in 1 2 3 4 5; do
  git "${PROXY[@]}" -c http.extraHeader="Authorization: Basic $AUTH" push -q origin HEAD:main && break
  echo "push failed (attempt $i), retrying..." >&2; sleep 3
done
HOOK=~/.config/trajectory-render/render_deploy_hook
if [[ -s $HOOK ]]; then curl -fsS -X POST "$(cat $HOOK)" >/dev/null && echo "render deploy triggered"; fi
echo "published"
