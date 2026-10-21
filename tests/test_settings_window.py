"""The Settings window builds, reflects changes in its preview, and saves what it shows."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from orbit.core import config as config_mod  # noqa: E402
from orbit.core import settings as st  # noqa: E402


def test_window_collects_toggles_order_and_gestures(tmp_path):
    from orbit.ui.settings_window import SettingsWindow
    app = QApplication.instance() or QApplication([])
    base, _ = config_mod.load(platform="windows")
    saved = []
    w = SettingsWindow(base, {}, True, "#7C9CFF", saved.append, settings_path=tmp_path / "s.json")
    first, second = w.order[0], w.order[1]
    w.rows[second].switch.setChecked(False)
    w.move(first, 1)
    w.gesture_boxes["triple"].setCurrentIndex(w.gesture_boxes["triple"].findData(st.OPEN_WHEEL))
    assert second not in [t for t, *_ in w.preview.items]
    w.save()
    s = saved[-1]
    assert s["wheel"]["order"][:2] == [second, first]
    assert second not in s["wheel"]["enabled"]
    assert s["gestures"]["triple"] == st.OPEN_WHEEL
    assert st.load(tmp_path / "s.json") == s
    app.processEvents()
