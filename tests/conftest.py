import os

import pytest


@pytest.fixture(autouse=True)
def _open_api_guard():
    """The local-API guard (Host + client-header checks) is for browser-origin
    traffic. The in-process test client is trusted, so open the guard for tests
    that exercise business logic. The dedicated guard test clears this itself.
    """
    prev = os.environ.get("XMAN_API_OPEN")
    os.environ["XMAN_API_OPEN"] = "1"
    yield
    if prev is None:
        os.environ.pop("XMAN_API_OPEN", None)
    else:
        os.environ["XMAN_API_OPEN"] = prev
