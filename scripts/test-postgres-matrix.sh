#!/usr/bin/env bash
set -Eeuo pipefail

compose_file="compose.integration.yml"

if (( $# > 0 )); then
  versions=("$@")
else
  versions=(14 15 16 17 18)
fi

cleanup() {
  docker compose -f "$compose_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

for version in "${versions[@]}"; do
  if [[ ! "$version" =~ ^(14|15|16|17|18)$ ]]; then
    echo "Unsupported PostgreSQL version: $version" >&2
    exit 2
  fi

  export POSTGRES_VERSION="$version"
  echo "Running integration tests against PostgreSQL $version"
  cleanup
  docker compose -f "$compose_file" up \
    --build \
    --abort-on-container-exit \
    --exit-code-from integration-tests \
    integration-tests
done

