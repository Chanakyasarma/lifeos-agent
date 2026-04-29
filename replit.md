# lifeos-agent

A small task tracking project with two parts:

1. **`backend/server.js`** — Express REST API for tasks (in-memory). This is the web-visible part of the project and runs on port 5000.
2. **`agent/agent.py`** — A Telegram bot that connects to Google Sheets to manage tasks. Requires the following secrets to run:
   - `TELEGRAM_TOKEN`
   - `CHAT_ID`
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_CREDS_JSON` (full service account JSON as a string)

The Telegram agent is **not** wired to a workflow because it requires the secrets above. Once those are provided you can run it manually via `python agent/agent.py`.

## Project layout

```
backend/server.js   Express API on port 5000 (host 0.0.0.0)
agent/agent.py      Telegram bot (Google Sheets-backed)
agent/streak.txt    Persisted streak counter
package.json        Node deps for the backend
```

## Running

- Backend: managed by the `Start application` workflow (`node backend/server.js`).
- Endpoints:
  - `GET /` — health/info
  - `GET /tasks`
  - `POST /tasks`
  - `PUT /tasks/:id`

## Deployment

Configured for **autoscale** deployment running `node backend/server.js`.

## Replit setup notes

- Node 20 + Python 3.12 modules are enabled in `.replit`.
- Express and CORS installed via npm (root `package.json`).
- The backend binds `0.0.0.0:5000` so the Replit preview proxy can reach it.
