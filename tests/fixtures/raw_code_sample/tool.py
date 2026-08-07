"""Fixture for orchestrate/onboarding/inspector.py's raw_code discovery
tests and sandbox_runner.py's real raw_code Docker execution tests — a
plain Python module with no MCP/OpenAPI markers at all."""


def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


def greet(name: str, greeting: str = "Hello") -> str:
    """Greet someone by name, with an optional custom greeting."""
    return f"{greeting}, {name}!"


def _private_helper() -> None:
    """Not eligible for discovery — underscore-prefixed."""
    return None


def attempt_outbound_request() -> str:
    """Try to reach a real external host — used to prove sandbox network
    isolation actually blocks this, not just assumed to."""
    import urllib.request

    with urllib.request.urlopen("https://example.com", timeout=5) as response:
        return f"reached example.com: {response.status}"
