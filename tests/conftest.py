import sys
from pathlib import Path

import pytest

# Add project root to Python path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@pytest.fixture(autouse=True)
def _disable_live_registry_agent(monkeypatch):
    """Unit/integration tests must never depend on Gemini or network state."""
    monkeypatch.setenv("REGISTRY_AGENT_MODE", "off")
