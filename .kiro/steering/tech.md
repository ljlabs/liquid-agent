# Technology Stack & Build System

## Backend Stack
- **Framework**: FastAPI (`>=0.110.0`)
- **Server**: Uvicorn with standard extras (`>=0.29.0`)
- **Data Validation**: Pydantic (`>=2.6.0`)
- **Database**: SQLite via aiosqlite (`>=0.20.0`) for session/message persistence
- **HTTP Client**: httpx (`>=0.27.0`) and requests (`>=2.31.0`)
- **SDK Integration**: Claude Agent SDK (shelled out via Claude Code CLI)

## Frontend Stack
- **UI Framework**: Vanilla JavaScript (ES modules, no build step required)
- **Testing**: Vitest (`^3.2.1`) with jsdom (`^26.1.0`)
- **Served by**: FastAPI's `StaticFiles` handler (single `index.html` entry point)

## Architecture
```
Backend (FastAPI + Claude SDK)
    ↓
Session Manager (in-memory + database)
    ↓
SSE Streaming (JSON events to browser)
    ↓
Frontend JavaScript (state management + DOM updates)
```

## Build & Development Commands

### Backend Setup
```bash
cd server
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate
pip install -r requirements.txt

# Optional: Install claude CLI separately (SDK can manage it)
# export ANTHROPIC_API_KEY=sk-ant-...
```

### Backend Run
```bash
cd server
# Windows: use python directly to ensure ProactorEventLoopPolicy
python app/main.py
# App runs at http://localhost:8787
```

### Backend Testing
```bash
cd server
pytest tests/                        # Run all tests
pytest -v tests/test_file.py::test_name  # Run specific test
pytest --cov=app tests/              # With coverage report
```

### Frontend Testing
```bash
cd server/app/static/js
npm test                             # Run tests once
npm run test:watch                   # Watch mode
```

### Development Notes
- **No frontend build step**: JavaScript is served directly from `static/` as ES modules
- **Hot reload**: FastAPI with `reload=True` watches backend files
- **Windows specific**: Always use `python app/main.py` on Windows (not `uvicorn`) to apply `WindowsProactorEventLoopPolicy`
- **Environment**: Requires `ANTHROPIC_API_KEY` for Claude SDK authentication

## Key Dependencies & Versions
- Python: 3.8+ (async/await, type hints)
- Node.js: 18+ (for frontend testing, optional for production)
- Claude Agent SDK: Via Claude Code CLI (managed externally)

## Configuration Files
- `requirements.txt`: Backend dependencies
- `requirements-dev.txt`: Development/test dependencies
- `server/app/static/js/package.json`: Frontend dependencies
- `server/pytest.ini`: Test configuration
- `server/system_prompt.md`: System prompt for Claude sessions
