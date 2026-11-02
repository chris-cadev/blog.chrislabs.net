# Observability: Analytics & Traceability

How blog-chat stays observable — web analytics (Umami) and end-to-end traceability logs.
This guide is written for every role: stakeholders, support, ops/SRE, and developers. Each
section explains *what to look for* and *how to find it*, at the level of detail that role needs.

---

## 1. TL;DR

- **Umami** (hosted at `latitudem2m-analytics.chrislabs.net`) tracks page views and key
  product events client-side. Dashboards live in the Umami UI.
- **Traceability logs** are a single stream of structured, one-line JSON records written to
  stdout. Every record carries a `request_id` that ties together an HTTP request, the user who
  made it, and everything logged while handling it.
- The response to every request includes an `X-Request-ID` header. If a user reports a problem,
  that ID is the key to finding their exact trace in the logs.

---

## 2. The log stream

### 2.1 Format

Set `LOG_FORMAT`:

| Value     | When to use                                   |
|-----------|-----------------------------------------------|
| `json`    | Production. One JSON object per line, parseable by any log collector (`jq`, Datadog, Loki). |
| `console` | Local development. Human-readable, colored output. |

A `json` record looks like:

```json
{"ts":"2026-08-04T17:42:11.123Z","level":"INFO","logger":"blog_chat.http","message":"http.request.complete","service":"blog_chat","env":"production","request_id":"9f2c1a4b7d3e08f1","method":"GET","path":"/en/hello-world","status":200,"duration_ms":42.3,"client_ip":"203.0.113.9","username":"CoolOtter-4821","user_agent":"Mozilla/5.0 ...","detail":"ops"}
```

### 2.2 Common fields

| Field        | Meaning                                                          |
|--------------|------------------------------------------------------------------|
| `ts`         | UTC timestamp, ISO-8601.                                         |
| `level`      | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.                 |
| `logger`     | Component that wrote the record (`blog_chat.http`, `blog_chat.chat`, `blog_chat.events`, ...). |
| `message`    | Human-readable summary.                                          |
| `service`    | Always `blog_chat`.                                              |
| `env`        | `development` or `production` (from `APP_ENV`).                  |
| `request_id` | Correlation ID for one HTTP request / WS session.                |
| `event`      | Machine-readable event name (see §2.3).                          |
| `detail`     | Audience hint: `business` (stakeholders) or `ops` (technical).   |
| `method`/`path`/`status`/`duration_ms` | Request lifecycle data.                      |
| `client_ip`/`user_agent`/`username` | Who made the request.                          |
| `exception`  | Formatted traceback, only on `ERROR`/`CRITICAL`.                 |

### 2.3 Event catalog

| Event                       | Emitted when                                             | Audience |
|-----------------------------|----------------------------------------------------------|----------|
| `page.view`                 | A blog page (index, tag, post) is served                 | business |
| `chat.message.sent`         | A chat message is persisted                              | business |
| `account.username_changed`  | A user renames themselves                                | business |
| `client.event`              | A client-side interaction beaconed to `/api/track` (post/tag clicks, theme toggle, language switch) — `client_event` field carries the event name | business |
| `http.request.complete`     | Any HTTP request finishes (has `status`, `duration_ms`)  | ops      |
| `http.request.error`        | An HTTP request raised an unhandled exception            | ops      |
| `http.request.start`        | Request begins (`DEBUG` level)                           | ops      |
| `chat.user.joined` / `chat.user.left` | WebSocket connect / disconnect               | ops      |
| `chat.connect.rejected`     | Room full, too many connections per IP                   | ops      |
| `chat.message.rejected`     | Message too long or rate-limited (`reason` field)        | ops      |
| `app.startup` / `app.shutdown` | Application lifecycle                              | ops      |

### 2.4 Request IDs end-to-end

1. The **Traceability middleware** reads an inbound `X-Request-ID` if present, otherwise
   generates one, and stamps it on the response header.
2. The ID is stored in a context variable, so **every log record written while serving that
   request carries the same `request_id`** — including DB work and business events.
3. A user hits an error? Ask them for the `X-Request-ID` from their browser's network tab
   (or the support header on the error page), then `grep` it in the logs.

---

## 3. Umami analytics

Umami is a privacy-friendly, self-hosted analytics platform. The tracker script is served from
`https://latitudem2m-analytics.chrislabs.net/script.js` and is loaded lazily by the app's own
bundle **only when analytics is enabled** (see §5). It is fully decoupled from the application
scripts: it is injected dynamically (`async`) after the app boots, so a slow or failing
analytics host can never block the chat or the traceability logs. It is configurable
per-environment, so it stays off in staging if you prefer.

### 3.1 What gets tracked automatically

- **Page views** of every page (path + referrer + device, handled by the tracker itself).
- **Custom events** (in the Umami dashboard under *Events*):

| Event               | When                                | Data                        |
|---------------------|-------------------------------------|-----------------------------|
| `Theme Toggle`      | User switches dark/light theme      | `theme`                     |
| `Language Switch`   | User switches en/es/fr              | `code`                      |
| `Post Click`        | User clicks a post link on the index| `slug`                      |
| `Tag Click`         | User clicks a tag filter            | `tag`                       |
| `Chat Message Sent` | User sends a chat message           | `room`                      |
| `Username Change`   | User renames themselves             | `username`                  |

### 3.2 Where the code lives

- Tracker metadata (`data-umami-*` on `<body>`, rendered only when enabled):
  `src/blog_chat/features/posts/templates/base.html`
- Tracker injection + event helper + queue: `src/blog_chat/core/client/umami.ts`
  (`initUmami()` in `core/client/main.ts`; safe no-op until the tracker loads)
- Event call sites: `core/client/theme.ts`, `core/client/main.ts`,
  `features/posts/client/main.ts`, `features/chat/client/ws-handlers.ts`
  (chat/posts use `window.trackUmami` so the bundles have zero analytics dependency)
- Every tracked client event is also beaconed to `POST /api/track`
  (`src/blog_chat/core/analytics.py`), which writes it into the trace stream as
  `client.event` — so every interaction (post/tag clicks, theme toggle, language
  switch, chat message, username change) is traceable server-side, in addition to
  the authoritative server events (`chat.message.sent`, `account.username_changed`).

---

## 4. Guides by role

### 4.1 Stakeholders / Product

**You care about:** *did people engage with the content?*

Use the **Umami dashboard** for traffic, top posts, referrers, and events. For raw activity in
the log stream, filter business events:

```bash
# all product events, newest first
journalctl -u blog-chat | grep '"event":"page.view"'
docker logs --tail 1000 blog-chat-app | grep '"detail":"business"'
```

Example questions answered here:
- How many times was each post viewed this week? → Umami *Pages* / `page.view` grouped by `slug`.
- How many chat messages per day? → `chat.message.sent` counts.
- Which languages do visitors use? → `Language Switch` event + Umami *Languages*.

### 4.2 Support

**You care about:** *a user says "it broke". What happened to them?*

1. Ask for the `X-Request-ID` (browser DevTools → Network tab → any request → Response Headers).
2. Search the logs:

```bash
docker logs blog-chat-app | grep "f3a9c21e6d04b087"
```

3. You now see the exact request: method, path, status, duration, and any error traceback.

If the user can't find a request ID, ask for:
- approximate time (UTC) of the problem, and
- their username — then search `"username":"CoolOtter-4821"`.

### 4.3 Ops / SRE

**You care about:** *is the service healthy? Latency? Error rates?*

The `ops` events give you the full request lifecycle. Typical checks:

```bash
# error rate (should be ~0)
docker logs blog-chat-app | grep '"level":"ERROR"'

# slow requests (>500ms)
docker logs blog-chat-app | jq -c 'select(.event=="http.request.complete" and .duration_ms>500)'

# rejected chat traffic (abuse / limits)
docker logs blog-chat-app | jq -c 'select(.event=="chat.message.rejected" or .event=="chat.connect.rejected")'

# recent errors with their trace
docker logs blog-chat-app | jq -c 'select(.level=="ERROR")' | tail -20
```

Deployment and runtime notes:
- Logs go to **stdout** (12-factor); the container's log driver (`docker compose logs`) collects them.
- Set `APP_ENV=production` and `LOG_FORMAT=json` in production.
- The Cloudflare tunnel terminator does not set `X-Request-ID`, so the app generates one per request.
- `http.request.complete` includes `duration_ms`; watch p95 against `db` or `gzip` heavy endpoints.

### 4.4 Developers

**You care about:** *how do I read this, and how do I add my own events?*

Development defaults are friendly: `LOG_FORMAT=console` (colored, aligned) and you can drop to
`LOG_LEVEL=DEBUG` to see `http.request.start` records and every internal step.

Adding an **ops event** (technical, e.g. "room full"):

```python
from blog_chat.core.logging import get_logger
logger = get_logger("chat")
logger.warning("chat.connect.rejected", extra={"event": "chat.connect.rejected", "room": room, "detail": "ops"})
```

Adding a **business event** (stakeholder-visible, e.g. "voting feature"):

```python
from blog_chat.core.logging import log_business_event
log_business_event("voting.cast", "Vote cast", post=slug, username=username)
```

Important: the extra fields must be JSON-serializable (str/int/float/bool/None). Do **not** log
raw JWT payloads, cookies, or anything PII beyond the `username` already in use.

Files you'll touch:
- `src/blog_chat/core/logging.py` — formatters, `configure_logging()`, `get_logger()`, `log_business_event()`.
- `src/blog_chat/core/tracing.py` — `TraceabilityMiddleware`, request-ID context.
- `src/blog_chat/app.py` — middleware registration, `build_csp()` (Umami host in CSP).

---

## 5. Configuration reference

| Variable           | Default                                      | Purpose                                   |
|--------------------|----------------------------------------------|-------------------------------------------|
| `APP_ENV`          | `development`                                | Log `env` field; default log format.      |
| `LOG_LEVEL`        | `INFO`                                       | Verbosity of the whole stream.            |
| `LOG_FORMAT`       | `console` (dev) / `json` (prod)              | Output shape.                             |
| `UMAMI_ENABLED`    | `true`                                       | Master switch for the tracker.            |
| `UMAMI_SCRIPT_URL` | `https://latitudem2m-analytics.chrislabs.net/script.js` | Tracker location.        |
| `UMAMI_RECORDER_URL` | `https://latitudem2m-analytics.chrislabs.net/recorder.js` | Replay/heatmap recorder location. |
| `UMAMI_WEBSITE_ID` | *(empty)*                                    | Umami site ID; analytics activates only when this is set. |

Dashboard per website: enable **Replays & Heatmaps** (sample rate `0.15`, mask `moderate`, block `.chat-panel, .sensitive`). Replays retained 30 days. Recorder loads via `data-umami-recorder` alongside `data-umami-script` (see `core/client/umami.ts:initUmami`).

Note: when analytics is active, the app's Content-Security-Policy is extended so the browser may
load the tracker script and beacon events back to the Umami host (`script-src` and `connect-src`).
