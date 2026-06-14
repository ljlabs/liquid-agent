# run.py
import sys
import asyncio
import os


os.environ["ANTHROPIC_BASE_URL"] = "http://localhost:8000"

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8787, reload=False)