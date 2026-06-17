# Tool/Function Calling Format Guide

This guide documents the different tool calling formats used by various LLM providers.

## OpenAI Format

OpenAI's Chat Completions API uses a nested structure with `type` and `function` wrappers:

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get the current weather in a location",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "City name"
            }
          },
          "required": ["location"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

**Key characteristics:**
- Each tool has `type: "function"` wrapper
- Function definition nested inside `function` object
- Uses JSON Schema for `parameters`
- Models: GPT-3.5, GPT-4, GPT-4o, o1, o3

**References:**
- [OpenAI Function Calling Guide](https://developers.openai.com/docs/guides/function-calling)
- [Tool Calls API](https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/tool-calls)

## Anthropic (Claude) Format

Anthropic's API uses a flatter structure with `input_schema`:

```json
{
  "tools": [
    {
      "name": "get_weather",
      "description": "Get the current weather in a location",
      "input_schema": {
        "type": "object",
        "properties": {
          "location": {
            "type": "string",
            "description": "City name"
          }
        },
        "required": ["location"]
      }
    }
  ]
}
```

**Key characteristics:**
- No `type` wrapper
- Uses `input_schema` instead of `parameters`
- Flatter structure
- Models: Claude 2, Claude 3 (Opus, Sonnet, Haiku), Claude 3.5

**References:**
- [Anthropic Tool Use Documentation](https://docs.anthropic.com/en/docs/tool-use)

## Google Gemini/Vertex AI Format

Google uses `function_declarations` in a `tools` array:

```json
{
  "tools": [
    {
      "function_declarations": [
        {
          "name": "get_weather",
          "description": "Get the current weather in a location",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {
                "type": "string",
                "description": "City name"
              }
            },
            "required": ["location"]
          }
        }
      ]
    }
  ]
}
```

**Key characteristics:**
- Tools contain `function_declarations` arrays
- Similar to OpenAI but with different nesting
- Uses `parameters` like OpenAI
- Models: Gemini 1.5 Pro, Gemini 1.5 Flash, Gemini 2.0, Gemma

**References:**
- [Vertex AI Function Calling](https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/function-calling)
- [Gemini API Function Calling](https://ai.google.dev/docs/function_calling)

## OpenAI-Compatible Proxies

Many proxy services (like the one at `localhost:8000`) expect the OpenAI format but may validate differently. Some proxies:
- Convert between formats internally
- May have looser validation
- Check the proxy's documentation for specific requirements

## Detection Strategy

When building multi-provider clients, detect the format based on model name:

```python
def get_tool_format(model_name: str) -> str:
    model_lower = model_name.lower()
    
    if "claude" in model_lower:
        return "anthropic"
    elif any(x in model_lower for x in ["gemini", "gemma"]):
        return "google"
    else:  # gpt, o1, o3, or generic
        return "openai"
```

## Common Issues

### MALFORMED_FUNCTION_CALL
- **Cause**: Wrong format sent to Gemini/Gemma models
- **Solution**: Use Google format or OpenAI-compatible format

### Missing "name" field
- **Cause**: Backend expects different nesting level for name field
- **Solution**: Check if backend uses custom format, not standard OpenAI

### Tool not recognized
- **Cause**: System prompt doesn't mention available tools
- **Solution**: List tools in system prompt or ensure they're in the tools array

## Content Attribution

Information compiled from official documentation:
- [OpenAI API Documentation](https://developers.openai.com/docs)
- [Anthropic Claude Documentation](https://docs.anthropic.com)
- [Google AI Developer Docs](https://ai.google.dev)
- [Vertex AI Documentation](https://cloud.google.com/vertex-ai/docs)

*Content was rephrased for compliance with licensing restrictions*
