# CMF Controller (Linux Native)

**Native Linux Controller for CMF Buds Pro 2 dial and Nothing Ecosystem.**

Turn the smart physical dial on your CMF Buds Pro 2 charging case into an unconstrained, continuous rotary controller on Linux (Wayland / KDE Plasma 6 / PipeWire).

Designed from scratch for Linux with **Obsidian Dark Glassmorphism** (`#0B0C0E`), **Nothing Signature Red** (`#D71921`), and a **48-dot knurled track**.

---

## Features

- **Continuous Virtual Rotary Encoder**:
  - Bypasses the hardware AVRCP `0..127` boundary freeze with automatic debounced idle recentering (`CENTER_VOL = 64`).
  - Enjoy infinite 360° rotation in both directions with zero volume locking.
- **Applications Sub-Wheel**:
  - Fast XDG `.desktop` app scanner.
  - Browse installed desktop applications with pagination (`Page X/Y »`), high-res artwork, and press-to-launch.
- **Zero Subprocess Overhead**:
  - Direct BlueZ D-Bus system bus listener (`org.bluez.MediaTransport1.Volume`) in steps of 8.
  - Sub-millisecond dial response with zero `pactl` lag or race conditions.
- **PipeWire / WirePlumber Decoupling**:
  - Decoupled via `~/.config/wireplumber/wireplumber.conf.d/50-cmf-buds.conf` (`bluez5.hw-volume = []`).
  - System audio volume never drifts, ducks, or jumps to laptop speakers.
- **Nothing Control Center GUI**:
  - Real-time CMF Buds battery gauges & ANC mode switcher (`[ ANC ]`, `[ Transparency ]`, `[ Off ]`).
  - Nothing Phone (4b) battery & "Ring My Phone" finder via KDE Connect.
  - Quick launch triggers.
- **Native Wayland Overlay**:
  - GPU-accelerated Qt Quick / QML overlay running natively on Wayland.
- **evdev Button Listener**:
  - Exclusive grab (`dev.grab()`) during wheel operations to prevent background media players from misfiring.

---

## Wheel Tools

1. **Volume**: Direct PipeWire master sink volume scaling with media play/pause on click.
2. **Applications**: Sub-wheel browsing all installed desktop applications.
3. **Brightness**: Display backlight stepping via KDE Plasma Solid PowerManagement D-Bus.
4. **Windows**: Fast application switching (`Alt+Tab` / `Alt+Shift+Tab`).
5. **Scroll**: Smooth Wayland high-resolution scrolling (`REL_WHEEL_HI_RES`).
6. **Workspaces**: Virtual desktop switching (`Meta+W` KDE Overview on click).
7. **ANC Mode**: RFCOMM packet dispatch cycling ANC, Transparency, and Off.
8. **Nothing Phone**: Triggers ring sound on connected Nothing Phone via KDE Connect.
9. **Undo / Redo**: Quick `Ctrl+Z` / `Ctrl+Y` actions.

---

## Controls

| Dial Gesture | When In Tool | When In Wheel | When In Apps Wheel |
|---|---|---|---|
| **Turn** | Adjust active tool (vol/scroll/etc) | Rotate tool selection | Browse installed applications |
| **Click** | Tool action / Play-Pause | Commit selected tool | Launch selected application |
| **Double Press** | Open main wheel | Dismiss wheel | Return to main wheel |
| **Hold** | Open main wheel | Dismiss wheel | Return to main wheel |
| **Triple Press** | Toggle ANC mode | Dismiss wheel | Return to main wheel |

---

## Installation & Running

### Requirements
- Python 3.10+
- `PySide6`, `evdev`, `dbus-python`, `PyGObject`

```bash
# Install dependencies (Garuda / Arch)
sudo pacman -S python-pyside6 python-evdev python-dbus python-gobject

# Run the controller daemon & tray icon
python3 -m cmf

# Or use the installed CLI wrapper
cmf-controller

# Launch specific views
cmf-controller --gui      # Open Nothing Control Center
cmf-controller --wheel    # Open Main Wheel
cmf-controller --apps     # Open Applications Wheel
cmf-controller --anc      # Cycle ANC mode
cmf-controller --ring     # Ring Nothing Phone
```

---

## License
MIT License
