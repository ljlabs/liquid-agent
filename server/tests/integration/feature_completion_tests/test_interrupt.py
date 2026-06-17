"""Tests: Interrupt functionality."""

import asyncio
import pytest
from unittest import mock
from app.sessions import Session, SessionManager
from app.view_data import ViewDataGenerator
from app import database as db
import app.main as main

from .conftest import MockLLMClient, create_session, get_view, wait_for_session_idle


@pytest.mark.asyncio
async def test_interrupt_stops_running_session(client, manager, view_gen):
    """Interrupt action sets session back to idle."""
    main.manager = manager
    main.view_generator = view_gen

    # Create a slow mock LLM
    class SlowMockLLM:
        def __init__(self, **kwargs):
            self.options = kwargs.get("options")
            self._queue = asyncio.Queue()

        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def query(self, content):
            await asyncio.sleep(5)  # Simulate slow response

        async def receive_response(self):
            while True:
                ev = await self._queue.get()
                yield ev
                if ev.get("type") == "message_stop":
                    break

    with mock.patch("app.sessions.CustomLLMWrapper", SlowMockLLM):

        sid = await create_session(client)
        # Send message (will be slow)
        asyncio.create_task(client.post("/v1/view", json={
            "action": "send_message", "session_id": sid, "message": "slow task",
        }))

        await asyncio.sleep(0.2)  # Let it start

        # Interrupt
        r = await client.post("/v1/view", json={
            "action": "interrupt", "session_id": sid,
        })
        assert r.status_code == 200

        await asyncio.sleep(0.5)

        view = await get_view(client, sid)
        assert view["active_session"]["status"] == "idle"


@pytest.mark.asyncio
async def test_interrupt_nonexistent_session(client):
    """Interrupt on nonexistent session doesn't crash."""
    r = await client.post("/v1/view", json={
        "action": "interrupt", "session_id": "nonexistent",
    })
    assert r.status_code == 200
