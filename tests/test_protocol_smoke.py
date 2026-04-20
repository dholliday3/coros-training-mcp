import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, stdio_client


@pytest.mark.anyio
async def test_stdio_server_initializes_and_lists_tools(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    env = {
        "HOME": str(tmp_path),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["server.py"],
        cwd=repo_root,
        env=env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()

    tool_names = {tool.name for tool in tools.tools}
    assert "list_workouts" in tool_names
    assert "get_workout" in tool_names
    assert "list_scheduled_workouts" in tool_names
    assert "move_scheduled_workout" in tool_names
    assert "update_workout" in tool_names
    assert "replace_scheduled_workout" in tool_names
    assert "get_run_workout_schema" in tool_names
    assert "create_run_workout" in tool_names
    assert "update_run_workout" in tool_names


@pytest.mark.anyio
async def test_stdio_server_returns_clean_auth_error_for_schedule_query(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    env = {
        "HOME": str(tmp_path),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["server.py"],
        cwd=repo_root,
        env=env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "list_scheduled_workouts",
                {"start_day": "20260420", "end_day": "20260427"},
            )

    assert result.isError is False
    assert result.structuredContent["scheduled_workouts"] == []
    assert "Not authenticated" in result.structuredContent["error"]
