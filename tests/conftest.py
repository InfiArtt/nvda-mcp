import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ADDON_PACKAGE = ROOT / "addon" / "globalPlugins" / "nvdaMcp"

# bridge.py and speechLog.py import nothing from NVDA, so they can be tested directly.
sys.path.insert(0, str(ADDON_PACKAGE))
sys.path.insert(0, str(ROOT))


@pytest.fixture
def anyio_backend():
    return "asyncio"
