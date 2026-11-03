import importlib
import sys

import controlApproval
import pytest

from nvda_mcp import server


@pytest.fixture(autouse=True)
def fresh_nvda():
    """Each test starts as if NVDA had just started."""
    sys.modules.pop(controlApproval._STATE_MODULE, None)
    yield
    sys.modules.pop(controlApproval._STATE_MODULE, None)


def reload_plugins():
    """What NVDA+control+F3 does to this add-on: its modules are imported again from scratch."""
    del sys.modules["controlApproval"]
    return importlib.import_module("controlApproval")


def test_approval_lasts_through_plugin_reloads():
    assert not controlApproval.isApproved()
    controlApproval.approve()
    reloaded = reload_plugins()
    assert reloaded.isApproved()
    assert not reloaded.wasRevoked()


def test_revoking_lasts_through_plugin_reloads_too():
    controlApproval.approve()
    controlApproval.revoke()
    reloaded = reload_plugins()
    assert not reloaded.isApproved()
    assert reloaded.wasRevoked()
    reloaded.approve()
    assert not reloaded.wasRevoked()


def test_an_action_must_start_while_the_client_still_waits():
    assert controlApproval.CLIENT_WAIT_SECONDS == server.PRESS_KEYS_TIMEOUT_SECONDS
    # With the default 3 seconds of listening, the user has well over a minute and a half to answer.
    deadline = controlApproval.startDeadline(1000.0, 3.0)
    assert deadline == 1000.0 + 120.0 - 10.0 - 3.0
    # Listening as long as allowed (timeout_ms 60000) still leaves time to answer.
    assert controlApproval.startDeadline(0.0, 60.0) >= controlApproval.MIN_ANSWER_SECONDS
