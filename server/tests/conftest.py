"""Shared fixtures for integration tests."""

import os
import socket
import threading
import time

import pytest
import uvicorn


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def mock_llm_server():
    """Start the mock LLM server in a background thread for the test session."""
    from tests.mock_llm_server import app as mock_app

    port = _free_port()
    config = uvicorn.Config(
        mock_app, host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait until the server is accepting connections
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)

    os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["ANTHROPIC_MODEL"] = "mock-model"
    os.environ["ANTHROPIC_API_KEY"] = "sk-no-key-needed"

    yield port

    server.should_exit = True
    thread.join(timeout=5)
