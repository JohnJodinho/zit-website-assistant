# Public API contract

Base path: `/api/v1`. Requests and JSON responses use UTF-8. Send
`Content-Type: application/json` on POST requests. Every response includes
`X-Request-ID`; the same ID is returned as `error.trace_id` for JSON errors and
as `meta.request_id` in the chat stream.

## Endpoints

### `GET /config`

No request body or authentication header.

Response `200`:

```json
{
  "enabled": true,
  "rollout_percent": 100,
  "maintenance_message": "ZIT assistant is temporarily unavailable.",
  "privacy_notice": "Do not enter personal or confidential information."
}
```

`enabled` is false when the kill switch is on or the rollout is zero. A client
must not start or continue a chat when it is false.

### `POST /sessions`

Creates a session. The token is returned once and must be kept by the client
until it expires.

Request:

```json
{"turnstile_token": null}
```

When `TURNSTILE_ENABLED=true`, provide the site-verification token instead.
With Turnstile disabled, the field may be omitted.

Response `200`:

```json
{"session_token": "<opaque-token>", "expires_in_minutes": 30}
```

The token expires after the returned interval (30 minutes by default). The
server stores only a keyed hash of it. Send it in the JSON body of chat,
feedback, and client-event requests; do not put it in a URL or log it.

### `POST /chat/stream`

Request:

```json
{
  "message": "What courses do you offer?",
  "session_token": "<opaque-token>"
}
```

`message` must contain 1–500 characters. The session token is required. The
response is `text/event-stream`, with `Cache-Control: no-cache`,
`X-Accel-Buffering: no`, and `X-Request-ID` headers. The stream uses standard
SSE frames (`event: name`, followed by one JSON `data:` line).

Events:

| Event | JSON data | Meaning |
|---|---|---|
| `ping` | `{}` | Keep-alive while retrieval or generation is in progress. |
| `meta` | `{"request_id":"<uuid>","release":2,"path":"...","intent":[],"links":{},"degraded":false}` | Request/retrieval metadata. `release` may be null; `links` maps link keys to `{ "label": "...", "url": "..." }`. A capacity fallback can emit a second `meta` with `path: "capacity"`. |
| `delta` | `{"t":"answer text"}` | Text to append to the current answer. One or more events may arrive. |
| `error` | `{"code":"partial_generation_failed"}` | The answer is incomplete. Output-limit truncation uses `generation_truncated`; validation can also emit `{"code":"answer_validation_failed"}`. |
| `done` | `{"finish":"stop","actions":[],"degraded":false}` | Normal stream end. `degraded` is true for fallback or error cases. |

During retrieval, zero or more `ping` events may arrive before `meta`. Once
retrieval completes, `meta` arrives before answer text. Then `delta` events
arrive, followed by `done`. A capacity fallback may send a second `meta` before
its `delta`. Provider errors or answer-validation failures after text has
started send `error` and then `done`; treat all preceding deltas as partial,
not as a complete answer. The API does not emit a separate `partial` event.
Disconnects can end a stream without `done`.

Errors before the stream starts use the common JSON error response below. The
client should stop reading the event stream after `done` or a transport error.

### `POST /feedback`

Stores a rating for a trace belonging to the supplied session.

Request:

```json
{
  "trace_id": "<meta.request_id>",
  "session_token": "<opaque-token>",
  "rating": 1
}
```

`rating` must be `-1`, `0`, or `1`.

Response `200`:

```json
{"status":"recorded","trace_id":"<uuid>"}
```

### `POST /client-events`

Records one supported client event against a trace belonging to the session.

Request:

```json
{
  "trace_id": "<meta.request_id>",
  "session_token": "<opaque-token>",
  "event": "response_error"
}
```

`event` is `response_error` or `feedback_submitted`.

Response `200`:

```json
{"status":"recorded"}
```

### `GET /health`

Liveness only; it does not check the database.

Response `200`:

```json
{"status":"ok"}
```

### `GET /ready`

Checks the database, migration state, and active release snapshot.

Response `200` when ready, or `503` otherwise:

```json
{
  "status": "ready",
  "database": "ready",
  "migration": "ready",
  "telemetry": {
    "queue_size": 0,
    "dropped_spans": 0,
    "dropped_traces": 0,
    "dropped_errors": 0
  },
  "release": "loaded",
  "snapshot_error": null
}
```

When unavailable, the status fields identify the failed check; `release` is
`not_loaded` if no active snapshot is available.

## Error response

All JSON HTTP errors use this shape and include the same `X-Request-ID` header:

```json
{
  "error": {
    "code": "invalid_or_expired_session",
    "message": "invalid_or_expired_session",
    "trace_id": "<uuid>"
  }
}
```

Validation errors return `422` with `code: "validation_error"` and do not echo
submitted values. Unexpected errors return `500` with `code: "internal_error"`.
Other endpoint errors use these status/code pairs:

| Status | Codes |
|---|---|
| `401` | `session_required`, `invalid_or_expired_session` |
| `403` | `turnstile_verification_failed` |
| `404` | `trace_not_found` |
| `409` | `session_request_in_progress` |
| `413` | `message_too_long` |
| `429` | `session_rate_limited`, `chat_rate_limited` |
| `503` | `assistant_not_available`, `assistant_not_in_rollout`, `session_service_not_configured`, `turnstile_not_configured`, `turnstile_temporarily_unavailable` |

## Session and origin handling

The session token is an opaque bearer credential in the JSON body, not an
`Authorization` header or cookie. It is generated from random bytes, hashed
with `SESSION_PEPPER` before storage, and expires after `expires_in_minutes`.
The default is 30 minutes. Create a new session after expiration.

Browser clients must use an exact allowed origin configured in
`WIDGET_ORIGINS`; wildcard origins are not accepted. The API allows `GET`,
`POST`, `PUT`, `PATCH`, and `DELETE`, and exposes `X-Request-ID`. Configure
`TRUSTED_PROXY_HOPS` only for the actual proxy chain; client IP rate limits
otherwise use the direct peer.

## Example: create a session and stream a question

This Bash example uses a reserved placeholder host; replace it with the API
origin when running it. The API must be ready, chat rollout must be enabled,
and `SESSION_PEPPER` must be configured.

```bash
API_BASE="https://api.example.invalid"
SESSION_TOKEN="$(curl -fsS -X POST "$API_BASE/api/v1/sessions" \
  -H "Content-Type: application/json" \
  -d '{}' | python -c 'import json,sys; print(json.load(sys.stdin)["session_token"])')"

curl -N -X POST "$API_BASE/api/v1/chat/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d "{\"message\":\"What courses do you offer?\",\"session_token\":\"$SESSION_TOKEN\"}"
```

## Frontend configuration

The client needs the backend origin, an exact allowed origin added to
`WIDGET_ORIGINS`, and the desired `TURNSTILE_ENABLED` setting. Turnstile is
disabled by default; when enabled, the client must send its verification token
to `POST /sessions`, and the backend must have `TURNSTILE_SECRET` configured.
