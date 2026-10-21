"""Keep tests off the machine's own Orbit files: a user config.toml / settings.json
(the macOS app copies its config to ~/Library/Application Support/Orbit) must not
change what the tests load."""
import pytest

from orbit.core import config as config_mod


@pytest.fixture(autouse=True)
def _no_user_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "user_config_path", lambda: tmp_path / "no-user-config" / "config.toml")
