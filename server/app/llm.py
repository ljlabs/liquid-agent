import os
import json
import logging
import httpx
from typing import AsyncIterator, List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class LLMResponse:
    def __init__(self, content: str = "", tool_calls: List[Dict[str, Any]] = None):
        self.content = content
        self.tool_calls = tool_calls or []

class CustomLLMWrapper:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = (
            api_key or 
            os.environ.get("ANTHROPIC_API_KEY") or 
            "sk-no-key-needed"
        )
        # Use Anthropic Messages API endpoint
        raw_base = base_url or os.environ.get("ANTHROPIC_BASE_URL") or "http://localhost:8000"
        self.base_url = raw_base.rstrip("/")
        
        self.model = (
            model or 
            os.environ.get("ANTHROPIC_MODEL") or 
            "default"
        )

    async def chat_completion(
        self, 
        messages: List[Dict[str, Any]], 
        system: Optional[str] = None,
        tools: List[Dict[str, Any]] = None,
        stream: bool = False
    ) -> AsyncIterator[Dict[str, Any]]:
        headers = {
            "Content-Type": "application/json"
        }
        
        # Build Anthropic Messages API request
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096
        }
        
        # Add system prompt if provided
        if system:
            payload["system"] = system
            logger.info(f"System prompt length: {len(system)}")
        
        # Add tools if provided
        if tools:
            payload["tools"] = tools
            logger.info(f"Sending {len(tools)} tools")
        
        # Use Anthropic Messages API endpoint
        url = f"{self.base_url}/v1/messages"
        logger.info(f"Sending request to {url}")

        async with httpx.AsyncClient(timeout=None) as client:
            # Anthropic Messages API - non-streaming only for now
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                logger.error(f"LLM Error: {response.status_code} - {response.text}")
                yield {"type": "error", "message": f"LLM Error: {response.status_code}"}
            else:
                # Return the full Anthropic Messages API response
                yield response.json()
