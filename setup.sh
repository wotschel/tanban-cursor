#!/usr/bin/env bash

set -euo pipefail

ENV_FILE=".env"
ENV_TEMPLATE=".env.example"

if [[ ! -f "$ENV_TEMPLATE" ]]; then
    printf 'Error: %s was not found. Run this script from the project root.\n' \
        "$ENV_TEMPLATE" >&2
    exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
    printf 'Error: openssl is required to generate secure secrets.\n' >&2
    exit 1
fi

if [[ "$(id -u)" == "0" || "$(id -g)" == "0" ]]; then
    printf 'Error: Run this script as your regular host user, not with sudo or as root.\n' >&2
    exit 1
fi

if [[ -e "$ENV_FILE" ]]; then
    read -r -p ".env already exists. Overwrite it? [y/N] " overwrite
    case "$overwrite" in
        y|Y|yes|YES) ;;
        *)
            printf 'Aborted. The existing .env was not changed.\n'
            exit 0
            ;;
    esac
fi

printf 'Select the environment:\n'
printf '  1) development\n'
printf '  2) test\n'
printf '  3) production\n'

while true; do
    read -r -p "Environment [1-3]: " environment_choice
    case "$environment_choice" in
        1|development)
            app_env="development"
            break
            ;;
        2|test)
            app_env="test"
            break
            ;;
        3|production)
            app_env="production"
            break
            ;;
        *) printf 'Error: Please select 1, 2, or 3.\n' >&2 ;;
    esac
done

secret_key="$(openssl rand -hex 48)"
mariadb_password="$(openssl rand -hex 32)"
mariadb_root_password="$(openssl rand -hex 32)"
app_uid="$(id -u)"
app_gid="$(id -g)"

cp "$ENV_TEMPLATE" "$ENV_FILE"

sed -i \
    -e "s|^APP_ENV=.*|APP_ENV=$app_env|" \
    -e "s|^SECRET_KEY=.*|SECRET_KEY=$secret_key|" \
    -e "s|^MARIADB_PASSWORD=.*|MARIADB_PASSWORD=$mariadb_password|" \
    -e "s|^MARIADB_ROOT_PASSWORD=.*|MARIADB_ROOT_PASSWORD=$mariadb_root_password|" \
    -e "s|^APP_UID=.*|APP_UID=$app_uid|" \
    -e "s|^APP_GID=.*|APP_GID=$app_gid|" \
    "$ENV_FILE"

chmod 600 "$ENV_FILE"

printf '\n.env created successfully for %s.\n' "$app_env"
printf 'Set TANBAN_* and CURSOR_API_KEY in .env before wiring integrations.\n'
printf 'The generated secrets are stored only in .env.\n'

read -r -p "Start the Docker build now? [y/N] " start_build
case "$start_build" in
    y|Y|yes|YES) start_build="yes" ;;
    *) start_build="no" ;;
esac

if [[ "$(id -u)" == "0" || "$(id -g)" == "0" ]]; then
    printf 'Error: Docker must not be started as root. Run the script as your regular host user.\n' >&2
    exit 1
fi

if [[ "$start_build" == "yes" ]]; then
    printf 'Starting Docker build...\n'
    printf 'Waiting until the app is healthy (migrations finished)...\n'
    if docker compose up --detach --build --wait --wait-timeout 180; then
        printf 'Docker build completed and containers are healthy.\n'
    else
        exit_code=$?
        printf 'Error: Docker build failed or services did not become healthy (exit code %d).\n' \
            "$exit_code" >&2
        exit "$exit_code"
    fi
else
    printf 'Build skipped. Start later with: docker compose up --detach --build --wait\n'
    exit 0
fi

printf '\nApp health: http://127.0.0.1:%s/health\n' "${APP_PORT:-8100}"
printf 'Webhook endpoint: POST http://127.0.0.1:%s/webhooks/tanban\n' "${APP_PORT:-8100}"
