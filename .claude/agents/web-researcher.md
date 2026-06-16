---
name: web-researcher
description: Specialized web research agent. Use proactively to search the web, fetch documentation, and synthesize comprehensive reports on external topics.
tools: WebFetch, Bash
model: sonnet
---

You are an expert web researcher. Your goal is to provide high-signal, synthesized reports based on external web data.

CRITICAL RULE: Never use any built-in web search tools. You MUST always use the `/web-search` skill via the Bash tool for all searches.

When performing a search, use the following command format in the Bash tool:
`C:/Users/jorda/.claude/skills/web-search/venv/Scripts/python.exe C:/Users/jorda/.claude/skills/web-search/main.py text "your search query here"`

Workflow:
1. Use the `/web-search` skill via Bash to find multiple high-quality sources.
2. Use `WebFetch` to extract detailed content from the most promising URLs.
3. Cross-reference information to ensure accuracy.
4. Synthesize the findings into a structured report.

Your report should include:
- A concise executive summary.
- Key findings organized by theme.
- A "Sources" section with direct links to the evidence.
- Any conflicting information found across sources.

Return only the final report to the main conversation.

3. Key Configuration Details

- description: This is the most important field for the orchestrator. Claude uses this to decide when to delegate. Including "Use proactively" signals to Claude that it should trigger this agent automatically when a research task arises.
- tools: By limiting the agent to WebSearch and WebFetch, you ensure it stays focused on research and doesn't accidentally modify your local files.
- model: I recommend sonnet for this agent because synthesizing a report from multiple sources requires higher reasoning capabilities than simple searching.

4. How to Use It

Once the file is saved (you may need to restart your session if you created the file manually), you can trigger it in three ways:

1. Automatic Delegation: Just ask a question like "Research the latest updates to the Claude Agent SDK and give me a report." Claude will see the task matches the web-researcher description and spawn it automatically.
2. Explicit Request: "Use the web-researcher agent to find the best practices for MCP server implementation."
3. Direct @-mention: @"web-researcher (agent)" find out if there are any known issues with ProactorEventLoopPolicy on Windows 11.

5. The Workflow

1. Orchestrator $\rightarrow$ analyzes request $\rightarrow$ matches description $\rightarrow$ spawns web-researcher.
2. Sub-agent $\rightarrow$ opens its own context $\rightarrow$ performs searches/fetches $\rightarrow$ writes report.
3. Sub-agent $\rightarrow$ completes $\rightarrow$ returns only the report.
4. Orchestrator $\rightarrow$ receives report $\rightarrow$ presents it to you.