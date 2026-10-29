# Frontend

React + Vite + Recharts UI for Wind Forecast Desk. See the
[main README](../README.md) for the full project description.

Run from this folder:

| Command | What it does |
|---|---|
| `npm ci` | Install dependencies |
| `npm run dev` | Dev server on http://localhost:5180, with `/api` forwarded to the backend on port 8001 (override with `API_PORT`) |
| `npm test` | Unit tests for display formatting (Node's built-in test runner) |
| `npm run lint` | Lint with oxlint |
| `npm run build` | Production build into `dist/`, which FastAPI serves |
