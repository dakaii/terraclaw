#!/usr/bin/env bash
# Build and push Terraclaw images to Artifact Registry.
# Usage: ./scripts/build-push.sh PROJECT_ID REGION REPOSITORY_ID [TAG]
set -euo pipefail

PROJECT="${1:?Usage: $0 PROJECT_ID REGION REPOSITORY_ID [TAG]}"
REGION="${2:?REGION}"
REPO="${3:?REPOSITORY_ID}"
TAG="${4:-latest}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REG="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

echo "Configuring docker auth for ${REGION}-docker.pkg.dev ..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" -q

echo "Building zeroclaw (Rust; first build can take 15–30+ minutes) ..."
docker build -t "${REG}/zeroclaw:${TAG}" -f "${ROOT}/containers/zeroclaw/Dockerfile" "${ROOT}/containers/zeroclaw"

echo "Building reflection ..."
docker build -t "${REG}/reflection:${TAG}" -f "${ROOT}/containers/reflection/Dockerfile" "${ROOT}/containers/reflection"

echo "Pushing ..."
docker push "${REG}/zeroclaw:${TAG}"
docker push "${REG}/reflection:${TAG}"

echo "Done."
echo "  ${REG}/zeroclaw:${TAG}"
echo "  ${REG}/reflection:${TAG}"
