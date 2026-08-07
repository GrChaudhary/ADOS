"""
Tiny real MCP-native server, used as a fixture for
orchestrate/onboarding/inspector.py and wrapper_generator.py's tests — not
mocked, an actual FastMCP server a real fastmcp.Client can connect to over
stdio, with no external dependencies or network access needed to run it.
"""

from fastmcp import FastMCP

mcp = FastMCP("echo-sample")


@mcp.tool
def echo_message(message: str) -> str:
    """Echo the given message back, unchanged."""
    return message


@mcp.tool
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


@mcp.tool
def send_welcome_back_message() -> str:
    """Send a welcome-back message to an employee returning from extended leave."""
    return "welcome-back message sent"


@mcp.tool
def attempt_outbound_request() -> str:
    """Try to reach a real external host — used to prove sandbox network
    isolation actually blocks this, not just assumed to."""
    import urllib.request

    with urllib.request.urlopen("https://example.com", timeout=5) as response:
        return f"reached example.com: {response.status}"


if __name__ == "__main__":
    mcp.run()
