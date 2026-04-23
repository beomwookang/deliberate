"""Basic tests for MCP tool definitions."""
import asyncio


def test_all_tools_registered() -> None:
    """Verify all 17 MCP tools are registered."""
    from deliberate_mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    expected = {
        "list_policies", "get_policy", "create_policy", "update_policy",
        "delete_policy", "test_policy",
        "list_approvers", "create_approver", "update_approver",
        "list_groups", "create_group", "update_group",
        "list_pending_approvals", "get_approval_status", "query_ledger",
        "list_api_keys", "create_api_key",
    }
    assert expected == tool_names, f"Missing: {expected - tool_names}, Extra: {tool_names - expected}"


def test_tool_descriptions_have_content() -> None:
    """Every tool should have a description with at least 20 chars."""
    from deliberate_mcp.server import mcp

    for tool in asyncio.run(mcp.list_tools()):
        desc = tool.description or ""
        assert len(desc) >= 20, f"Tool {tool.name} has too short a description: {desc!r}"
