# TanBan ↔ Cursor Bridge

Kleiner Integrationsdienst zwischen TanBan und anderen Systemen.
Erster Adapter: **Cursor** (API / Agents SDK).

## Stack

- Python 3.13 / FastAPI / Uvicorn
- MariaDB + SQLAlchemy + Alembic
- Docker Compose
- `httpx` für TanBan Board-API
- `cursor-sdk` für Cursor Agents

## Schnellstart

```bash
./setup.sh
# oder manuell:
cp .env.example .env   # Secrets setzen
docker compose up --detach --build --wait
curl -s http://127.0.0.1:8100/health
```

Port default: `8100` (damit er nicht mit TanBan auf `8000` kollidiert).

## Dispatch-Regel

Bei `card_created` und `card_labels_changed`:

1. Label **cursor** gesetzt?
2. Zusätzlich **plan** oder **work** gesetzt? (`work` hat Vorrang)
3. Mindestens eines dieser Labels wurde in diesem Event **hinzugefügt**?
4. → Prompt an **Cursor Cloud** (`CURSOR_REPOSITORY`)

Unrelated Label-Änderungen bei bereits gesetztem Combo lösen keinen neuen Run aus.
Aktive Runs (`pending`/`running`) für dieselbe Card+Mode werden nicht verdoppelt.

## Konfiguration

| Variable | Zweck |
|---|---|
| `TANBAN_BASE_URL` | Basis-URL der TanBan-Instanz |
| `TANBAN_API_KEY` | Board-API-Key (`tbk_…`), Scope i.d.R. `read_write` |
| `TANBAN_BOARD_ID` | Numerische Board-ID (Label-Auflösung über `/api/cards`) |
| `TANBAN_WEBHOOK_SECRET` | Signing-Secret aus `webhook-create` (`tbwh_…`) |
| `CURSOR_API_KEY` | Cursor API-Key (Dashboard → Integrations) |
| `CURSOR_MODEL` | z.B. `composer-2.5` |
| `CURSOR_REPOSITORY` | Repo-URL für Cloud-Agents |
| `CURSOR_RUNTIME` | `cloud` (Dispatch erzwingt cloud) |

## Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/health` | Healthcheck |
| `POST` | `/webhooks/tanban` | Empfang ausgehender TanBan-Board-Webhooks |

TanBan signiert mit `X-TanBan-Signature: sha256=…` sowie
`X-TanBan-Event` / `X-TanBan-Delivery`. Deliveries werden idempotent in
`inbound_webhook_events` gespeichert.

### Webhook in TanBan eintragen

```bash
cd /opt/tanban
docker compose exec app python manage.py webhook-create <board_id> \
  --name cursor-bridge \
  --url http://host.docker.internal:8100/webhooks/tanban
# Secret (tbwh_…) in tanban-cursor .env als TANBAN_WEBHOOK_SECRET setzen
```

Host-Cron auf TanBan weiter nutzen (`webhook-deliver`), damit Events ankommen.

## CLI

```bash
./manage.sh health
./manage.sh webhook-list
./manage.sh run-list
```

## Nächste Schritte

1. Ergebnis zurück nach TanBan (Kommentar / Card-Update via Board-API)
2. Labels `cursor` / `plan` / `work` am Board anlegen
3. `CURSOR_API_KEY`, `CURSOR_REPOSITORY`, `TANBAN_BOARD_ID` in `.env` setzen
