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

1. Label **c-ask**, **c-plan** oder **c-work** gesetzt? (Priorität: `c-work` > `c-plan` > `c-ask`)
2. Dieses Mode-Label wurde in diesem Event **hinzugefügt**?
3. Card sperren mit Reason `cursor ask` / `cursor plan` / `cursor work`
4. Wenn `CURSOR_ACTIVE=true` → Prompt an **Cursor Cloud** (`CURSOR_REPOSITORY`); sonst nur loggen
5. Bei Mode **c-ask**: Agent-Antwort als Kommentar auf die Card

Unrelated Label-Änderungen bei bereits gesetztem Mode lösen keinen neuen Run aus.
Aktive Runs (`pending`/`running`) für dieselbe Card+Mode werden nicht verdoppelt.

## Konfiguration

Mehrere Boards mit `c-ask` / `c-plan` / `c-work` können dieselbe Bridge nutzen.
TanBan-Keys und Webhook-Secrets sind **pro Board** — deshalb eine Map:

| Variable | Zweck |
|---|---|
| `TANBAN_BASE_URL` | Basis-URL der TanBan-Instanz |
| `TANBAN_BOARDS` | JSON: `board.public_id` → `{board_id, api_key, webhook_secret}` |
| `TANBAN_API_KEY` | Legacy Einzelboard: Board-API-Key (`tbk_…`, `read_write`) |
| `TANBAN_BOARD_ID` | Legacy: numerische Board-ID |
| `TANBAN_BOARD_PUBLIC_ID` | Legacy: `board.public_id` (macht Legacy zum Map-Eintrag) |
| `TANBAN_WEBHOOK_SECRET` | Legacy: Signing-Secret (`tbwh_…`) |
| `CURSOR_ACTIVE` | `true` = scharf (an Cursor senden); `false` = nur loggen |
| `CURSOR_API_KEY` | Cursor API-Key (Dashboard → Integrations) |
| `CURSOR_MODEL` | z.B. `composer-2.5` |
| `CURSOR_REPOSITORY` | Repo-URL für Cloud-Agents |
| `CURSOR_RUNTIME` | `cloud` (Dispatch erzwingt cloud) |

`TANBAN_BOARDS` (einzeilig), Beispiel:

```bash
TANBAN_BOARDS={"<public_id_a>":{"board_id":3,"api_key":"tbk_…","webhook_secret":"tbwh_…"},"<public_id_b>":{"board_id":4,"api_key":"tbk_…","webhook_secret":"tbwh_…"}}
```

Unbekannte `board.public_id` in der Map → Webhook-Signatur **401**.

## Endpunkte

| Methode | Pfad | Beschreibung |
|---|---|---|
| `GET` | `/health` | Healthcheck |
| `POST` | `/webhooks/tanban` | Empfang ausgehender TanBan-Board-Webhooks |

TanBan signiert mit `X-TanBan-Signature: sha256=…` sowie
`X-TanBan-Event` / `X-TanBan-Delivery`. Deliveries werden idempotent in
`inbound_webhook_events` gespeichert.

### Webhook in TanBan eintragen

Beide Stacks teilen das Docker-Netzwerk `tanban-shared` (Alias `tanban-cursor`).
TanBan-`compose.yaml` MUSS den App-Service an `shared` / `tanban-shared`
hängen — sonst kann TanBan den Hostnamen `tanban-cursor` nicht auflösen.

```bash
docker network create tanban-shared   # einmalig
cd /opt/tanban
docker compose up --detach --wait     # nach compose-Änderung: recreate app
# pro Board: API-Key + Webhook (gleiche Bridge-URL)
docker compose exec app python manage.py board-api-key-create <board_id> \
  --name cursor-bridge --scope read_write --actor <admin>
docker compose exec app python manage.py webhook-create <board_id> \
  --name cursor-bridge \
  --url http://tanban-cursor:8000/webhooks/tanban
# public_id, board_id, tbk_… und tbwh_… in TANBAN_BOARDS der Bridge eintragen
```

Host-Cron auf TanBan weiter nutzen (`webhook-deliver`), damit Events ankommen.
`webhook-deliver` mit `attempted=0` bedeutet nur „keine fälligen Jobs“ — Exit 0
ist dann kein Beweis, dass die Bridge etwas empfangen hat. Ob Events
ankommen: `docker compose logs -f app` in `tanban-cursor`.

Logs der eingehenden Events:

```bash
cd /opt/tanban-cursor && docker compose logs -f app
```

## CLI

```bash
./manage.sh health
./manage.sh webhook-list
./manage.sh run-list
```

## Nächste Schritte

1. Ergebnis zurück nach TanBan auch für `c-plan` / `c-work` (Kommentar / Card-Update)
2. Labels `c-ask` / `c-plan` / `c-work` auf jedem gewünschten Board anlegen
3. `CURSOR_API_KEY`, `CURSOR_REPOSITORY`, `TANBAN_BOARDS` in `.env` setzen
