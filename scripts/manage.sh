#!/usr/bin/env bash

set -euo pipefail

# Thin wrapper around `python manage.py` in the app container.
# Usage:
#   ./manage.sh health
#   ./manage.sh help

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

run_manage() {
    local -a docker_exec=(docker compose exec)
    if [[ -t 1 && -r /dev/tty ]]; then
        docker_exec+=(-it)
        "${docker_exec[@]}" app python manage.py "$@" </dev/tty
    else
        docker_exec+=(-T)
        "${docker_exec[@]}" app python manage.py "$@" </dev/null
    fi
}

if ! docker compose exec -T app true </dev/null >/dev/null 2>&1; then
    printf 'Error: App container is not running. Start the stack with: docker compose up -d\n' >&2
    exit 1
fi

if [[ $# -gt 0 ]]; then
    run_manage "$@"
    exit $?
fi

printf "Type 'help' for command list.\n"
while true; do
    printf 'manage> '
    if ! IFS= read -r line </dev/tty; then
        printf '\n'
        exit 0
    fi
    # shellcheck disable=SC2086
    set -- $line
    if [[ $# -eq 0 ]]; then
        continue
    fi
    case "$1" in
        exit|quit|q) exit 0 ;;
        help)
            run_manage help || true
            ;;
        *)
            run_manage "$@" || true
            ;;
    esac
done
