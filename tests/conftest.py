import pytest
import time

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Prevent time.sleep from slowing down tests."""
    monkeypatch.setattr(time, "sleep", lambda x: None)
