# TanBan ↔ Cursor Bridge – technische und funktionale Spezifikation

**Status:** konsolidierter Soll-Zustand (Stand Implementierung)  
**Version:** 1.0  
**Ziel:** schlanker Integrationsdienst, der ausgehende TanBan-Board-Webhooks entgegennimmt und bei Mode-Labels Cursor-Cloud-Agents startet.

Dieses Dokument ist die normative Produkt- und Implementierungsvorgabe für
`tanban-cursor`. Betriebsanleitung und Schnellstart stehen in `README.md`.

## 1. Geltungsbereich und Begriffe

Die Schlüsselwörter **MUSS**, **DARF NICHT**, **SOLL**, **SOLL NICHT** und
**KANN** sind normativ zu verstehen.

- **Bridge:** dieser Dienst (`tanban-cursor`).
- **TanBan:** die Kanban-Anwendung, die outbound Board-Webhooks sendet und
  über Board-API-Keys Schreibzugriff auf Cards erlaubt.
- **Mode-Label:** eines der Labels `c-ask`, `c-plan`, `c-work` auf einer Card.
- **Mode:** das aus den Mode-Labels aufgelöste Ergebnis; Priorität
  `c-work` > `c-plan` > `c-ask`.
- **Delivery:** eine einzelne TanBan-Webhook-Zustellung, identifiziert über
  `X-TanBan-Delivery` bzw. Payload-`id`.
- **Agent-Run:** persistierter Datensatz, der eine Card+Mode-Kombination mit
  einem Cursor-Agentenlauf verknüpft.
- **Dry-Run:** Betrieb mit `CURSOR_ACTIVE=false`; Labels werden ausgewertet und
  Runs erzeugt, aber kein Cursor-Agent gestartet.

Nicht Bestandteil dieser Spezifikation:

- die TanBan-Produktspezifikation selbst,
- die interne Cursor-Cloud-Implementierung,
- UI/Frontend der Bridge (es gibt keines).

## 2. Architektur und Tech-Stack

### 2.1 Komponenten

Das System MUSS aus mindestens zwei getrennten Containern bestehen:

1. **App-Container** – FastAPI/Uvicorn, Alembic-Migrationen, CLI.
2. **Datenbank-Container** – MariaDB; Daten außerhalb des Container-FS.

Die Bridge SOLL über das externe Docker-Netzwerk `tanban-shared` mit dem
Alias `tanban-cursor` erreichbar sein, damit TanBan Webhooks intern zustellen
kann.

### 2.2 Technologien

- Python 3.13
- FastAPI + Uvicorn
- SQLAlchemy ORM + Alembic
- MariaDB
- `httpx` für TanBan Board-API
- `cursor-sdk` für Cursor Cloud Agents
- pytest für Tests
- Docker Compose zur Orchestrierung

### 2.3 HTTP-Oberfläche

Die Bridge MUSS bereitstellen:

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/health` | Healthcheck |
| `GET` | `/` | Service-Hinweis mit Endpunktliste |
| `POST` | `/webhooks/tanban` | Empfang TanBan-Board-Webhooks |

Die Bridge DARF NICHT eine öffentliche HTML-UI bereitstellen.
OpenAPI unter `/docs` KANN verfügbar sein (Framework-Default).

Host-Port-Default: `8100` → Container-Port `8000` (Bind nur auf `127.0.0.1`,
zusätzlich erreichbar über `tanban-shared`).

### 2.4 Sicherheits-Header

Jede HTTP-Antwort MUSS mindestens setzen:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `X-Frame-Options: DENY`

## 3. Konfiguration

Beim Start MUSS optional eine `.env` geladen werden. Bereits gesetzte
Umgebungsvariablen MÜSSEN Vorrang haben. `.env` DARF NICHT versioniert werden;
`.env.example` MUSS alle Schlüssel ohne echte Geheimnisse dokumentieren.

| Variable | Pflicht | Default / Hinweis |
|---|---|---|
| `APP_ENV` | nein | `development` |
| `SECRET_KEY` | in `production` ja | Dev-Fallback nur außerhalb Production |
| `DATABASE_URL` | ja | Compose setzt sie aus MariaDB-Variablen |
| `APP_PORT` | nein | `8100` (Host-Mapping) |
| `TANBAN_BASE_URL` | für Dispatch-Schreibzugriff | ohne trailing slash |
| `TANBAN_BOARDS` | empfohlen (Multi-Board) | JSON-Objekt: `public_id` → `{board_id, api_key, webhook_secret}` |
| `TANBAN_API_KEY` | Legacy Einzelboard | Board-API-Key `tbk_…` |
| `TANBAN_BOARD_ID` | Legacy Einzelboard | positive ganze Zahl |
| `TANBAN_BOARD_PUBLIC_ID` | Legacy mit Map-Eintrag | `board.public_id` aus Webhook-Payload |
| `TANBAN_WEBHOOK_SECRET` | Legacy / Dev | `tbwh_…`; leer = Signaturprüfung aus (nur Dev) |
| `CURSOR_ACTIVE` | nein | `false` |
| `CURSOR_API_KEY` | wenn scharf | Cursor Dashboard |
| `CURSOR_MODEL` | nein | `composer-2.5` |
| `CURSOR_RUNTIME` | nein | `cloud` oder `local`; Dispatch erzwingt cloud |
| `CURSOR_REPOSITORY` | wenn scharf | Repo-URL für Cloud-Agents |
| `ACTIVITY_LOG_PATH` | nein | Log-Pfad im Container |

Wenn `TANBAN_BOARDS` gesetzt ist, MUSS es ein nicht-leeres JSON-Objekt sein.
Jedes Board in der Map MUSS eine positive `board_id` haben. Die Bridge MUSS
Credentials über `payload.board.public_id` auflösen (TanBan-API-Keys und
Webhook-Secrets sind pro Board).

Legacy: sind nur `TANBAN_BOARD_ID` / `TANBAN_API_KEY` / `TANBAN_WEBHOOK_SECRET`
gesetzt und `TANBAN_BOARDS` leer, KANN die Bridge im Einzelboard-Modus alle
Signaturen gegen dieses eine Secret prüfen und dieses eine `board_id` für
Card-Lookups verwenden. Mit zusätzlich `TANBAN_BOARD_PUBLIC_ID` SOLL daraus
ein normaler Map-Eintrag werden.

Ungültige Werte (z. B. `CURSOR_RUNTIME`, `CURSOR_ACTIVE`, `TANBAN_BOARDS`)
MÜSSEN beim Start mit klarer Fehlermeldung abgelehnt werden.

In Compose MÜSSEN `MARIADB_PASSWORD`, `MARIADB_ROOT_PASSWORD` und `SECRET_KEY`
gesetzt sein.

## 4. Persistenz

### 4.1 Allgemein

- Schemaänderungen MÜSSEN über Alembic erfolgen.
- Zeitstempel MÜSSEN timezone-aware in UTC gespeichert werden.
- Fachliche Schreiboperationen MÜSSEN transaktional erfolgen.

### 4.2 Tabelle `inbound_webhook_events`

Zweck: idempotente Speicherung eingehender Deliveries.

Pflichtfelder:

- `delivery_id` – eindeutig
- `event`
- `payload_json`
- `processed` (Default `false`)
- `received_at`

Optionale Felder: `board_public_id`, `object_public_id`, `process_error`,
`processed_at`.

### 4.3 Tabelle `cursor_agent_runs`

Zweck: Nachverfolgung von Cursor-Läufen pro Card/Mode.

Pflichtfelder:

- `status` (Default `pending`)
- `created_at`, `updated_at`

Optionale Felder: `board_public_id`, `card_public_id`, `mode`,
`content_hash`, `cursor_agent_id`, `cursor_run_id`, `prompt`, `result_text`,
`error`, `source_delivery_id`.

Bekannte Statuswerte: `pending`, `creating`, `running`, `finished`,
`skipped`, `error` (sowie vom SDK gelieferte Endzustände).

`content_hash` ist der SHA-256-Fingerprint aus Mode + normalisiertem Titel +
Beschreibung und dient der Content-Deduplizierung (siehe §6.4).

## 5. Webhook-Empfang

### 5.1 Signatur und Header

TanBan signiert mit HMAC-SHA256 über den Raw-Body:

- Header: `X-TanBan-Signature: sha256=<hex>`
- Event: `X-TanBan-Event`
- Delivery: `X-TanBan-Delivery`

Wenn mindestens ein Webhook-Secret konfiguriert ist, MUSS die Bridge die
Signatur mit konstantzeitigem Vergleich prüfen und bei Fehlschlag mit `401`
ablehnen. Bei Multi-Board-Map MUSS das Secret zum `board.public_id` im Body
passen; unbekannte Boards MÜSSEN mit `401` abgelehnt werden. Wenn kein Secret
konfiguriert ist, KANN die Prüfung entfallen (nur Entwicklung).

Fehlende Delivery-ID oder Event-Name MUSS zu `400` führen.
Ungültiges JSON MUSS zu `400` führen.

### 5.2 Idempotenz und ACK

Die Bridge MUSS jede Delivery unter `delivery_id` speichern.
Bereits bekannte Deliveries MÜSSEN als Duplikat erkannt werden
(`duplicate=true` in der Antwort) und DARFEN NICHT erneut dispatchen.

Erfolgreiche Annahme MUSS antworten mit:

```json
{"status":"ok","delivery_id":"…","duplicate":false}
```

Die HTTP-Antwort MUSS schnell erfolgen; die fachliche Verarbeitung SOLL im
Hintergrund (`BackgroundTasks`) laufen.

### 5.3 Logging

Eingehende Events SOLLEN strukturiert geloggt werden (Event, Delivery, Board,
Objekt, Label-Diff) sowie der vollständige Payload als JSON-Zeile.

## 6. Dispatch-Regeln

### 6.1 Relevante Events

Nur `card_created` und `card_labels_changed` MÜSSEN dispatch-fähig sein.
Andere Events MÜSSEN als verarbeitet markiert und ignoriert werden.

Das Payload-Objekt MUSS `object.type == "card"` sein (case-insensitive),
sonst Skip.

### 6.2 Label-Auswertung

1. Aktuelle Label-Namen der Card ermitteln.
2. Mode auflösen: `c-work` > `c-plan` > `c-ask`; keines → kein Dispatch.
3. Dispatch nur, wenn das aufgelöste Mode-Label in `labels.added` dieser
   Delivery enthalten ist.
4. Unrelated Label-Änderungen bei bereits gesetztem Mode lösen keinen neuen
   Run aus.

Label-Vergleiche MÜSSEN case-insensitive und getrimmt erfolgen.

### 6.3 Card-/Label-Auflösung

Die Bridge MUSS das Board über `payload.board.public_id` gegen die
konfigurierte Board-Map (oder Legacy-Einzelboard) auflösen. Ohne Credentials
für dieses Board MUSS der Dispatch übersprungen werden.

Mit bekannter numerischer `board_id` MUSS die Bridge die Card über die TanBan
Board-API per Card-`public_id` laden und aktuelle Labels sowie numerische `id`
verwenden (nötig für Blocken und Kommentare). Der Board-API-Key des
aufgelösten Boards MUSS verwendet werden.

Ohne `board_id`:

- bei `card_created` KANN auf `labels.added` im Payload zurückgefallen werden;
- bei `card_labels_changed` MUSS mit Fehler übersprungen werden.

### 6.4 Deduplizierung aktiver Runs und unveränderten Inhalts

Existiert bereits ein Run für dieselbe `card_public_id` und denselben `mode`
mit Status in `{pending, running, creating}`, DARF kein neuer Run gestartet
werden. Die Delivery MUSS dennoch als verarbeitet gelten.

Existiert bereits ein Run für dieselbe `card_public_id`, denselben `mode` und
denselben `content_hash`, bei dem `cursor_agent_id` gesetzt ist (Inhalt wurde
bereits an Cursor übergeben), DARF kein neuer Run gestartet werden. Das gilt
auch, wenn das Mode-Label entfernt und unverändert erneut gesetzt wird.
Dry-Run- oder Config-/Block-Fehler ohne `cursor_agent_id` MÜSSEN einen erneuten
Versuch mit gleichem Inhalt erlauben. Geänderte Titel- oder
Beschreibungsinhalte erzeugen einen neuen Hash und DÜRFEN erneut dispatchen.

### 6.5 Ablauf bei positivem Dispatch

1. `CursorAgentRun` mit Status `pending`, generiertem Prompt und
   `content_hash` anlegen.
2. Wenn `CURSOR_ACTIVE=false` → Status `skipped`, Dry-Run-Log, Ende.
3. Wenn `CURSOR_API_KEY` oder `CURSOR_REPOSITORY` fehlen → `skipped`/`error`
   dokumentieren, Ende.
4. Card in TanBan blocken mit Reason:
   - `c-ask` → `cursor ask`
   - `c-plan` → `cursor plan`
   - `c-work` → `cursor work`  
   Block-Fehler → Run `error`, Ende.
5. Cursor Cloud Agent starten (`runtime=cloud`, konfiguriertes Model/Repo).
6. Run mit Agent-/Run-IDs, Status und Ergebnistext aktualisieren.
7. Nur bei Mode `c-ask`: Ergebnis als Card-Kommentar posten
   (`Cursor ask:\n\n…`). Fehlender Text oder fehlende Card-ID → fataler
   Fehler; reiner API-Post-Fehler behält den Cursor-Status und setzt
   `error`.
8. Delivery als verarbeitet markieren.

### 6.6 Prompt-Inhalte

Jeder Prompt MUSS Card-`public_id`, Titel und Beschreibung enthalten.

| Mode | Auftrag an den Agenten |
|---|---|
| `c-ask` | Frage beantworten; Code lesen erlaubt; keine Implementierung, kein Plan; Antwort wird als Kommentar gepostet |
| `c-plan` | konkreten Implementierungsplan erzeugen; noch nicht implementieren |
| `c-work` | Card im Repo umsetzen; fokussierter Diff; kurze Zusammenfassung |

## 7. Integrationen

### 7.1 TanBan Board-API

Die Bridge SOLL mindestens können:

- Card per Board-ID + `public_id` finden,
- Card blocken (`blocked` + Reason),
- Kommentar an Card anhängen.

Authentifizierung über Bearer Board-API-Key (`TANBAN_API_KEY`).

### 7.2 Cursor SDK

Dispatch MUSS Cloud-Agents nutzen (`CURSOR_REPOSITORY` erforderlich).
`CURSOR_RUNTIME=local` KANN konfigurierbar sein, DARF den Dispatch aber nicht
von Cloud abweichen lassen, solange die Spec den Cloud-Pfad als Soll setzt.

## 8. CLI

Über `./manage.sh` bzw. `python manage.py` MÜSSEN verfügbar sein:

- `health` – Konfigurationsübersicht (Secrets nur als set/unset)
- `webhook-list` – letzte inbound Deliveries
- `run-list` – letzte Agent-Runs
- `help`

## 9. Betrieb

### 9.1 Start

```bash
./setup.sh
# oder
cp .env.example .env   # Secrets setzen
docker network create tanban-shared   # einmalig, falls nötig
docker compose up --detach --build --wait
```

Der App-Container MUSS vor dem Start von Uvicorn `alembic upgrade head`
ausführen.

### 9.2 Health

`GET /health` MUSS bei laufendem Dienst `status=ok` und `app_env` liefern.
Compose-Healthchecks MÜSSEN App und DB abdecken.

### 9.3 TanBan-Webhook eintragen

TanBan MUSS eine Outbound-Subscription auf
`http://tanban-cursor:8000/webhooks/tanban` haben. Das Signing-Secret MUSS in
`TANBAN_WEBHOOK_SECRET` der Bridge liegen. Host-seitiges `webhook-deliver` in
TanBan bleibt Voraussetzung für die Zustellung.

Der TanBan-App-Container MUSS dem externen Netzwerk `tanban-shared`
angehören, damit DNS `tanban-cursor` auflösbar ist. `webhook-deliver` mit
`attempted=0` gilt nicht als erfolgreiche Zustellung an die Bridge.

## 10. Tests

Mindestens MÜSSEN abgedeckt sein:

- Webhook-Signatur erzeugen/prüfen,
- Label-Regeln (Priorität, Added-Gate, Skip ohne Mode),
- Content-Hash-Stabilität und Skip bei bereits übermitteltem unverändertem Inhalt.

Weitere Integrationstests KANNEN ergänzt werden.

## 11. Bekannte Lücken / geplante Erweiterungen

Diese Punkte sind bewusst noch nicht Soll der v1.0-Kernpflicht:

1. Ergebnis zurück nach TanBan auch für `c-plan` / `c-work` (Kommentar oder
   Card-Update).
2. Explizites Unblock der Card nach Agent-Ende.
3. Asynchrones Polling/Webhooks von Cursor-Läufen (heute: synchrone
   `prompt_once`-Semantik im Hintergrund-Task).
4. Board-Labels `c-ask` / `c-plan` / `c-work` sind in TanBan manuell
   anzulegen; die Bridge erzeugt sie nicht.
