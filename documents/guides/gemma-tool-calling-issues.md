# Gemma/Gemini Tool Calling Issues

## Problem
When using Gemma-4-31b through the Route.llm proxy, the model returns:
```
finish_reason: "function_call_filter: MALFORMED_FUNCTION_CALL"
```

The model understands it should use the Bash tool but fails to generate a properly formatted function call.

## Root Cause
Google's Gemini/Gemma models have specific requirements for tool calling that differ from Anthropic's format:

1. **Native Google Format**: Uses `function_declarations` nested inside `tools` array
2. **Proxy Translation**: Route.llm converts Anthropic format → Google format
3. **Model Limitations**: Gemma models sometimes struggle with function calling even with correct format

## Request Format (What We Send)
```json
{
  "model": "claude-sonnet-4-6",
  "messages": [...],
  "tools": [
    {
      "name": "Bash",
      "description": "Run a shell command and return its output.",
      "input_schema": {
        "type": "object",
        "properties": {
          "command": {"type": "string", "description": "The shell command to run."}
        },
        "required": ["command"]
      }
    }
  ]
}
```

This is the **Anthropic format**, which Route.llm should convert to Google's format.

## What Google Expects
```json
{
  "tools": [
    {
      "function_declarations": [
        {
          "name": "Bash",
          "description": "Run a shell command and return its output.",
          "parameters": {
            "type": "object",
            "properties": {
              "command": {"type": "string", "description": "The shell command to run."}
            },
            "required": ["command"]
          }
        }
      ]
    }
  ]
}
```

## Possible Solutions

### 1. Check Route.llm Configuration
Ensure Route.llm is properly converting tools for Google models:
- Check the provider mapping for `claude-sonnet-4-6` → actual backend
- Verify tool translation logic for Google models
- Check if model name affects conversion

### 2. Use a Different Model
Try models with better tool calling support:
- `claude-3-5-sonnet-20241022` (if proxied to Anthropic)
- `gpt-4o` (if proxied to OpenAI)
- `gemini-2.0-flash-exp` (newer Gemini with better tool calling)

### 3. Direct API Call
Bypass Route.llm and call Google AI directly:
```python
# Use Google's generativeai SDK directly
import google.generativeai as genai
model = genai.GenerativeModel('gemini-2.0-flash-exp')
```

### 4. Simplify Tool Descriptions
Some models struggle with complex tool schemas. Try:
- Shorter descriptions
- Fewer properties
- Simpler parameter types

### 5. Check Route.llm Logs
The proxy should show what it's sending to Google. Check for:
- Tool conversion errors
- Format validation issues
- Model compatibility warnings

## Testing Strategy

1. **Test with Claude directly**: Change model to actual Claude model to verify app works
2. **Test with different Gemini model**: Try `gemini-2.0-flash-exp` instead of `gemma-4-31b`
3. **Test without tools**: Remove tools to verify basic streaming works
4. **Check proxy logs**: See what Route.llm is sending to Google backend

## References
- [Route.llm GitHub](https://github.com/ljlabs/Route.llm)
- [Google AI Function Calling Docs](https://ai.google.dev/docs/function_calling)
- [Gemini API Tool Use](https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/function-calling)

## Status
**Current**: Gemma-4-31b fails with MALFORMED_FUNCTION_CALL
**Next Steps**: 
1. Check Route.llm tool conversion for Google models
2. Try gemini-2.0-flash-exp instead
3. Verify proxy configuration
