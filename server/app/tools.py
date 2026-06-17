import os
import subprocess
import glob
import re
from typing import Any, Dict, List, Optional

class ToolResult:
    def __init__(self, output: str = "", error: str = "", is_error: bool = False):
        self.output = output
        self.error = error
        self.is_error = is_error

class BaseTool:
    name: str
    description: str
    parameters: Dict[str, Any]

    async def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError()

class ReadTool(BaseTool):
    name = "Read"
    description = "Read the content of a file. Optionally specify start and end lines (1-indexed)."
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file to read."},
            "start_line": {"type": "integer", "description": "Optional: The line number to start reading from (inclusive)."},
            "end_line": {"type": "integer", "description": "Optional: The line number to end reading at (inclusive)."}
        },
        "required": ["path"]
    }

    async def execute(self, path: str, start_line: int = None, end_line: int = None, cwd: str = None) -> ToolResult:
        full_path = os.path.join(cwd or os.getcwd(), path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if start_line is not None or end_line is not None:
                    start = (start_line - 1) if start_line is not None else 0
                    end = end_line if end_line is not None else len(lines)
                    return ToolResult(output="".join(lines[start:end]))
                return ToolResult(output="".join(lines))
        except Exception as e:
            return ToolResult(error=str(e), is_error=True)

class WriteTool(BaseTool):
    name = "Write"
    description = "Write complete content to a file. Overwrites if it exists."
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file."},
            "content": {"type": "string", "description": "The complete content to write."}
        },
        "required": ["path", "content"]
    }

    async def execute(self, path: str, content: str, cwd: str = None) -> ToolResult:
        full_path = os.path.join(cwd or os.getcwd(), path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
                return ToolResult(output=f"Successfully wrote to {path}")
        except Exception as e:
            return ToolResult(error=str(e), is_error=True)

class BashTool(BaseTool):
    name = "Bash"
    description = "Run a shell command and return its output."
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run."}
        },
        "required": ["command"]
    }

    async def execute(self, command: str, cwd: str = None) -> ToolResult:
        try:
            # Use Git Bash on Windows for better bash compatibility
            import sys
            if sys.platform == "win32":
                # Try to find Git Bash
                git_bash_paths = [
                    r"C:\Program Files\Git\bin\bash.exe",
                    r"C:\Program Files (x86)\Git\bin\bash.exe",
                    os.path.expandvars(r"%PROGRAMFILES%\Git\bin\bash.exe"),
                    os.path.expandvars(r"%PROGRAMFILES(X86)%\Git\bin\bash.exe"),
                ]
                
                bash_exe = None
                for path in git_bash_paths:
                    if os.path.exists(path):
                        bash_exe = path
                        break
                
                if bash_exe:
                    # Run via Git Bash with -c flag
                    result = subprocess.run(
                        [bash_exe, "-c", command],
                        capture_output=True,
                        text=True,
                        cwd=cwd or os.getcwd(),
                        timeout=30
                    )
                else:
                    # Fallback to cmd.exe if Git Bash not found
                    return ToolResult(
                        error="Git Bash not found. Please install Git for Windows from https://git-scm.com/download/win",
                        is_error=True
                    )
            else:
                # Use bash on Unix/Linux/Mac
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=cwd or os.getcwd(),
                    timeout=30
                )
            if result.returncode == 0:
                return ToolResult(output=result.stdout + result.stderr)
            else:
                return ToolResult(output=result.stdout, error=result.stderr, is_error=True)
        except Exception as e:
            return ToolResult(error=str(e), is_error=True)

class GlobTool(BaseTool):
    name = "Glob"
    description = "Find files matching a pattern recursively."
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "The glob pattern to match (e.g. '**/*.py')."}
        },
        "required": ["pattern"]
    }

    async def execute(self, pattern: str, cwd: str = None) -> ToolResult:
        try:
            files = glob.glob(pattern, root_dir=cwd, recursive=True)
            return ToolResult(output="\n".join(files))
        except Exception as e:
            return ToolResult(error=str(e), is_error=True)

class GrepTool(BaseTool):
    name = "Grep"
    description = "Search for a regex pattern in files."
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "The regex pattern to search for."},
            "path": {"type": "string", "description": "The directory or file to search in."}
        },
        "required": ["pattern", "path"]
    }

    async def execute(self, pattern: str, path: str, cwd: str = None) -> ToolResult:
        full_path = os.path.join(cwd or os.getcwd(), path)
        try:
            result = subprocess.run(
                ["grep", "-r", "-n", pattern, full_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            return ToolResult(output=result.stdout + result.stderr)
        except Exception as e:
            return ToolResult(error=str(e), is_error=True)

class WebFetchTool(BaseTool):
    name = "WebFetch"
    description = "Fetch the text content of a URL."
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to fetch."}
        },
        "required": ["url"]
    }

    async def execute(self, url: str, cwd: str = None) -> ToolResult:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                res = await client.get(url)
                return ToolResult(output=res.text[:10000])
        except Exception as e:
            return ToolResult(error=str(e), is_error=True)

class ReplaceTool(BaseTool):
    name = "Replace"
    description = "Surgical edit: Replace exact old_string with new_string in a file."
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The path to the file."},
            "old_string": {"type": "string", "description": "The exact literal text to replace."},
            "new_string": {"type": "string", "description": "The new text to replace it with."}
        },
        "required": ["path", "old_string", "new_string"]
    }

    async def execute(self, path: str, old_string: str, new_string: str, cwd: str = None) -> ToolResult:
        full_path = os.path.join(cwd or os.getcwd(), path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if old_string not in content:
                return ToolResult(error=f"Could not find exact match for 'old_string' in {path}", is_error=True)
            
            if content.count(old_string) > 1:
                return ToolResult(error=f"Found multiple matches for 'old_string' in {path}. Please provide more context.", is_error=True)
            
            new_content = content.replace(old_string, new_string)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            
            return ToolResult(output=f"Successfully replaced text in {path}")
        except Exception as e:
            return ToolResult(error=str(e), is_error=True)

class DelegateTool(BaseTool):
    name = "Delegate"
    description = "Delegate a sub-task to a new agent instance."
    parameters = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "The task for the sub-agent."}
        },
        "required": ["task"]
    }

    async def execute(self, task: str, cwd: str = None) -> ToolResult:
        return ToolResult(output=f"[Sub-Agent] Completed task: {task}")

ALL_TOOLS = [ReadTool(), WriteTool(), ReplaceTool(), BashTool(), GlobTool(), GrepTool(), WebFetchTool(), DelegateTool()]

def get_tool_definitions(format: str = "anthropic") -> List[Dict[str, Any]]:
    """Return tool definitions matching Claude Code's format.
    
    Uses Anthropic's format by default (name, description, input_schema).
    """

    x =  [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters  # Use full parameters object directly
        }
        for tool in ALL_TOOLS
    ]
    print("all tools", x)
    return x

async def execute_tool(name: str, args: Dict[str, Any], cwd: str = None) -> ToolResult:
    for tool in ALL_TOOLS:
        if tool.name == name:
            return await tool.execute(**args, cwd=cwd)
    return ToolResult(error=f"Tool {name} not found", is_error=True)
