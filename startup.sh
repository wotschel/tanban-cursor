#!/bin/bash
set -euo pipefail

no_cache=0
for arg in "$@"; do
  case "$arg" in
    --no-cache) no_cache=1 ;;
    -h|--help)
      printf 'Usage: %s [--no-cache]\n' "$(basename "$0")"
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\nUsage: %s [--no-cache]\n' "$arg" "$(basename "$0")" >&2
      exit 1
      ;;
  esac
done

if [[ "$no_cache" -eq 1 ]]; then
  docker compose build --no-cache app
else
  docker compose build app
fi
docker compose up --detach
docker compose logs --follow app
