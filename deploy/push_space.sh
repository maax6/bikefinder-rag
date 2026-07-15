#!/bin/bash
# Assemble the HF Space repo layout in a staging dir and upload it.
# Requires a prior `hf auth login` (write token). Usage:
#     deploy/push_space.sh <user>/<space-name>
#
# Space layout mirrors what deploy/Dockerfile expects as build context:
#     Dockerfile  README.md  pyproject.toml  src/  deploy/{entrypoint.sh,pgdata.tar.gz}
set -euo pipefail
cd "$(dirname "$0")/.."

SPACE_ID=${1:?usage: deploy/push_space.sh <user>/<space-name>}
HF=.venv/bin/hf

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

cp deploy/Dockerfile "$STAGE/Dockerfile"
cp deploy/space-README.md "$STAGE/README.md"
cp pyproject.toml "$STAGE/"
cp -R src "$STAGE/src"
mkdir -p "$STAGE/deploy"
cp deploy/entrypoint.sh deploy/pgdata.tar.gz "$STAGE/deploy/"

"$HF" repo create "$SPACE_ID" --repo-type space --space-sdk docker 2>/dev/null || true
"$HF" upload "$SPACE_ID" "$STAGE" . --repo-type space --commit-message "Deploy bikefinder-rag Space"

echo "Pushed. Build logs: https://huggingface.co/spaces/$SPACE_ID"
