---
name: integration-test-setup
description: Scaffold an integration test suite with mocked API server, load generator, and real-time monitoring dashboard
---

# Integration Test Setup

Creates a complete integration test environment under `<project>/integration/` with four components:

1. **Mocked API server** — Python HTTP server that mimics an upstream API (e.g., OpenAI-compatible). Returns canned responses for every request. Runs on a configurable port.

2. **Load generator** — Python script that sends concurrent requests to the system under test, collects latency/throughput metrics, and writes results to a JSON file.

3. **Real-time dashboard** — Single-file HTML+JS dashboard (no build step) that reads metrics and displays TPS, latency percentiles, and error rates via Chart.js. Served by a simple Python HTTP server.

4. **Serve script** — Starts the dashboard server and opens it in the browser.

## Procedure

1. **Create directory**: `mkdir -p <project>/integration/`

2. **Write mock server** (`mock_server.py`):
   - Subclass `http.server.BaseHTTPRequestHandler`
   - Accept POST on any path, return a canned JSON response with configurable delay
   - Support `--port` flag (default 8081)
   - Log request count and timing

3. **Write load generator** (`load_test.py`):
   - Accept `--target-url`, `--concurrency`, `--duration` flags
   - Use `threading` or `asyncio` for parallel requests
   - Collect per-request latency, status codes, errors
   - Write results to `results.json` every N seconds
   - Support graceful shutdown on SIGINT

4. **Write dashboard** (`dashboard.html`):
   - Single HTML file with inline CSS and JS (or separate `dashboard.js`)
   - Use Chart.js CDN for real-time charts
   - Display: TPS (actual vs target), latency P50/P95/P99, error rate
   - Poll `results.json` every 2 seconds
   - **Critical**: Use proper JS object syntax: `{ label: 'X', data: [] }` not `{ label: 'X',  [], b...`

5. **Write serve script** (`serve_dashboard.py`):
   - Start `http.server.HTTPServer` on port 8080
   - Serve `integration/` directory
   - Print URL to console

6. **Write orchestrator** (`run_integration.py`):
   - Start mock server in a subprocess
   - Start load generator in a subprocess
   - Start dashboard server in a subprocess
   - Wait for all, handle SIGINT to clean up

## Common Pitfalls

- **JS syntax in dashboard**: When writing Chart.js config inline, always use `{ label: 'name', data: [] }` with proper commas. Bare `[], b` after a label causes syntax errors that are hard to spot.
- **Port conflicts**: Default ports 8080 (dashboard) and 8081 (mock server). Make them configurable.
- **File paths on Windows**: Use forward slashes in Python strings (`C:/path/to/file`) to avoid escape issues.

## Stopping Condition

All four files exist in `<project>/integration/` and `python run_integration.py` starts without import errors.
