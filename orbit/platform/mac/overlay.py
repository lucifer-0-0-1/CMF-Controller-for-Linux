"""Make the Qt Quick overlay behave like a macOS HUD panel.

QWindow.winId() on Cocoa is an NSView; its .window() is the NSWindow (an NSPanel
for Qt.Tool). Settings per docs/research-macos.md section 5:
  - status level + join all spaces + full-screen auxiliary: shows over full-screen apps
  - ignores mouse: click-through; never hides on deactivate (we're an agent app)
Re-applied every time Qt shows the window, since Qt may reconfigure it.
"""
from __future__ import annotations

import logging

log = logging.getLogger("orbit.overlay")


def macify(qwindow) -> None:
    try:
        import objc
        from AppKit import (NSStatusWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
                            NSWindowCollectionBehaviorFullScreenAuxiliary, NSWindowCollectionBehaviorIgnoresCycle,
                            NSWindowCollectionBehaviorStationary)
        view = objc.objc_object(c_void_p=int(qwindow.winId()))
        w = view.window()
        if w is None:
            return
        w.setLevel_(NSStatusWindowLevel)
        w.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | NSWindowCollectionBehaviorFullScreenAuxiliary
                                 | NSWindowCollectionBehaviorStationary
                                 | NSWindowCollectionBehaviorIgnoresCycle)
        w.setIgnoresMouseEvents_(True)
        w.setHidesOnDeactivate_(False)
        w.setCanHide_(False)
        w.setOpaque_(False)
        w.setHasShadow_(False)
        if qwindow.isVisible():
            w.orderFrontRegardless()
    except Exception:
        log.exception("could not adjust overlay window")


def make_agent_app() -> None:
    """No Dock icon / app menu (like LSUIElement), required for overlays over full-screen spaces."""
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(1)   # NSApplicationActivationPolicyAccessory
    except Exception:
        log.exception("could not switch to accessory app")


def ensure_accessibility(prompt: bool = True) -> bool:
    """Posting key/scroll events silently fails without the Accessibility permission."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        ok = bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))
    except Exception:
        log.exception("accessibility check failed")
        return False
    if not ok:
        log.warning("Accessibility permission missing: System Settings > Privacy & Security > "
                    "Accessibility > enable Orbit (or your terminal/Python), then restart Orbit")
    return ok
