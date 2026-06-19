# Product Overview

## Purpose
A browser-based AI agent interface that wraps the Claude Agent SDK, enabling users to interact with Claude through a VS Code extension-style web UI. The system manages agent sessions, handles tool permissions, and streams responses via Server-Sent Events (SSE).

## Key Features
- **Multi-session management**: In-memory session handling with optional SQLite persistence
- **Permission framework**: Granular control over tool execution with three permission modes
  - `default`: Users approve/deny each tool use
  - `acceptEdits`: Auto-approve edits and filesystem operations
  - `bypassPermissions`: Auto-approve all tools
  - `plan`: Read-only mode with limited tool execution
- **Real-time streaming**: SSE-based response streaming with text, thinking, and tool use events
- **Tool permission rules**: Per-tool allow/ask/deny rules, persistent and configurable per session
- **Message persistence**: SQLite database stores sessions and message history
- **Planning mode**: Experimental read-only mode for exploring solutions without side effects

## User Personas
- Developers using Claude for code generation and analysis
- Power users who need to restrict tool access (e.g., deny file writes)
- Teams evaluating AI agent workflows with controlled permissions

## Core Interactions
1. User sends a message via the web UI
2. Session manager routes to appropriate Claude SDK client
3. Agent executes with permission constraints
4. Results stream back to UI with tool use, permissions, and thinking
5. User approves/denies pending permissions, receives tool results
