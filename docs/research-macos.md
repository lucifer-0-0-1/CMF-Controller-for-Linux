# Orbit on macOS: Backend Research (PyObjC, macOS 13-15, Apple Silicon)

Collected Oct 2026. Nothing here has been tested on a Mac with the CMF Buds Pro 2 yet.

Confidence tags used below:
- **[doc]**: stated in Apple documentation or headers.
- **[src]**: shown by a well-known open-source project or a developer-forum thread.
- **[belief]**: general platform knowledge. Likely true, but no primary source was found in this pass.
- **[spec]**: speculative. Must be tested on hardware before we rely on it.

PyObjC packages used: `pyobjc-core`, `pyobjc-framework-Cocoa` (AppKit/Foundation), `-Quartz` (CGEvent, CGDisplay), `-MediaPlayer`, `-AVFoundation`, `-ApplicationServices` (AX), `-ServiceManagement`, `-CoreAudio`.
Note: the PyObjC docs say the CoreAudio binding is low-level, has no examples, and may not work well from Python ("fairly low-level ... no examples", https://pyobjc.readthedocs.io/en/latest/apinotes/CoreAudio.html). **Recommendation: call the CoreAudio HAL C API through `ctypes`** (sketch below), and use PyObjC for everything that is Objective-C.

---

## 1. Rotation: listening to the buds' output volume (CoreAudio HAL)

### API
- Framework: `CoreAudio.framework` (HAL, `AudioHardware.h`). Optionally `AudioToolbox.framework` (`AudioHardwareService*`).
- Enumerate devices: `AudioObjectGetPropertyData(kAudioObjectSystemObject (=1), {kAudioHardwarePropertyDevices 'dev#', kAudioObjectPropertyScopeGlobal 'glob', kAudioObjectPropertyElementMain 0})` returns an array of `AudioObjectID`. [doc]
- For each device, read:
  - `kAudioObjectPropertyName` ('lnam', a CFString) for the name, e.g. "CMF Buds Pro 2".
  - `kAudioDevicePropertyDeviceUID` ('uid ', a CFString). For Bluetooth devices the UID contains the BT address, which makes it a more stable key than the name. [belief]
  - `kAudioDevicePropertyTransportType` ('tran') `== kAudioDeviceTransportTypeBluetooth` ('blue'). LE Audio uses 'blea'. [doc]
  - Has output streams: `kAudioDevicePropertyStreams` ('stm#') with scope `kAudioObjectPropertyScopeOutput` ('outp'), size > 0.
- Volume properties, both with scope output:
  - `kAudioDevicePropertyVolumeScalar` ('volm', Float32 0..1). It may exist only on element 1 and 2 (left/right channels), not on element 0 (main). Check `AudioObjectHasProperty` for elements 0, 1 and 2. [doc/belief]
  - `kAudioHardwareServiceDeviceProperty_VirtualMainVolume` ('vmvc', Float32 0..1). Before macOS 12 it was called `...VirtualMasterVolume`. This is the single "system volume" that the menu-bar slider shows, and it works whether the device has a main control or only per-channel controls. Use it through `AudioHardwareServiceGetPropertyData` / `SetPropertyData` / `AddPropertyListener` (AudioToolbox). [doc] https://developer.apple.com/documentation/audiotoolbox/kaudiohardwareservicedeviceproperty_virtualmainvolume
  - Also useful: `kAudioDevicePropertyMute` ('mute'). Some devices map volume 0 to mute.
- Listener: `AudioObjectAddPropertyListener(objID, &addr, AudioObjectPropertyListenerProc, clientData)`, or the block variant `AudioObjectAddPropertyListenerBlock(objID, &addr, dispatch_queue, block)`. [doc] https://developer.apple.com/documentation/coreaudio/1422472-audioobjectaddpropertylistener
- Set the volume back with `AudioHardwareServiceSetPropertyData(dev, &vmvcAddr, 0, NULL, 4, &f32)`, or `AudioObjectSetPropertyData` on 'volm' for each channel.
- Hot-plug: also listen on the system object for `kAudioHardwarePropertyDevices` and `kAudioHardwarePropertyDefaultOutputDevice` ('dOut'). The buds get a **new AudioObjectID on every reconnect**, so re-resolve the device by UID or name each time.

### Does an AVRCP absolute-volume change from the buds update this property?
- **[belief, high confidence, must verify]** Yes. macOS supports AVRCP 1.4+ absolute volume for A2DP sinks. When the headset changes volume (AirPods Max crown, Sony/Bose buttons), the Mac's system volume slider moves. That slider is the device's VirtualMainVolume, so a listener on 'vmvc' (and on 'volm' per channel) should fire. Run test 1 in the checklist at the end to confirm this for the CMF buds.
- macOS uses AVRCP's 0..127 absolute volume. The buds step by about 1/16 of the range, so expect scalar deltas of about 0.06. Derive the step count from the delta (`round(delta / step)`) instead of counting callbacks: CoreAudio can coalesce or split notifications, and 'volm' on L and R fires twice per step.
- **Echo:** when Orbit restores the volume, the listener fires again, and macOS sends AVRCP SetAbsoluteVolume back to the buds. Handle this the same way as on Windows: keep a "pending restore" value and ignore the notification that matches it. **[spec]** Whether the buds' 0.3 s rate limit also applies to volume changes the Mac pushes to the buds needs testing.
- Endpoints: at 0.0 or 1.0 the buds stop sending steps in one direction. This is the same issue as on Windows.

### Volume HUD (OSD)
- **[belief]** macOS 13-15 show the volume HUD (OSDUIHelper bezel) for hardware-key volume changes. For volume changes that come from the Bluetooth headset itself, the HUD is commonly reported for AirPods. Not verified for third-party buds.
- **[belief]** Setting volume through CoreAudio (or `osascript -e 'set volume output volume N'`) does **not** show the HUD (https://techearl.com/mac-volume-command-line). So Orbit's restore step should be silent. Any flash would come from the buds' own change.
- No public API suppresses the HUD. Older tricks (`launchctl unload` of OSDUIHelper/BezelUI) need SIP disabled and no longer work (https://csc.ucdavis.edu/~jmahoney/macosx.html, Apple Community https://discussions.apple.com/thread/251133728). **Do not attempt this.** If the HUD does flash on every click, accept it. Orbit's own wheel overlay is drawn on top anyway.

### Threading / run loop
- By default the HAL delivers C-proc listeners on a HAL-owned notification thread. To make that explicit, set `kAudioHardwarePropertyRunLoop` ('rnlp') on the system object to NULL early in startup, which tells the HAL to use its own thread. [doc, header comment in AudioHardware.h]
- A ctypes `CFUNCTYPE` callback takes the GIL automatically. Do nothing heavy inside it: read the value and emit a Qt signal. Signals across threads are queued, so the handler runs on the Qt main thread.
- Keep a module-level reference to the ctypes callback object, or it gets garbage-collected and the process crashes.
- Do not call `AudioObjectSetPropertyData` from inside the listener. Post the restore to the main thread or a worker thread.

### Permissions
None. Reading and setting output volume needs no TCC permission. **Never open the buds' input device**: that would trigger the Microphone TCC prompt and switch the buds from A2DP to HFP (mono, low quality).

### Sketch (ctypes)
```python
import ctypes, struct
from ctypes import c_uint32, c_int32, c_void_p, c_float, POINTER, byref, sizeof, CFUNCTYPE
CA  = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
AT  = ctypes.CDLL("/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox")
CF  = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
fcc = lambda s: struct.unpack(">I", s.encode())[0]

class Addr(ctypes.Structure):
    _fields_ = [("sel", c_uint32), ("scope", c_uint32), ("elem", c_uint32)]

SYS, GLOB, OUT, MAIN = 1, fcc("glob"), fcc("outp"), 0
DEVICES, NAME, VMVC, VOLM = fcc("dev#"), fcc("lnam"), fcc("vmvc"), fcc("volm")

def devices():
    a = Addr(DEVICES, GLOB, MAIN); size = c_uint32()
    CA.AudioObjectGetPropertyDataSize(SYS, byref(a), 0, None, byref(size))
    ids = (c_uint32 * (size.value // 4))()
    CA.AudioObjectGetPropertyData(SYS, byref(a), 0, None, byref(size), ids)
    return list(ids)

def name(dev):
    a = Addr(NAME, GLOB, MAIN); ref = c_void_p(); size = c_uint32(sizeof(c_void_p))
    CA.AudioObjectGetPropertyData(dev, byref(a), 0, None, byref(size), byref(ref))
    import objc; s = objc.objc_object(c_void_p=ref.value)  # CFString -> NSString
    out = str(s); CF.CFRelease(ref); return out

def find(substr):
    return next(d for d in devices() if substr.lower() in name(d).lower())

def get_vol(dev):
    a = Addr(VMVC, OUT, MAIN); v = c_float(); size = c_uint32(4)
    AT.AudioHardwareServiceGetPropertyData(dev, byref(a), 0, None, byref(size), byref(v))
    return v.value

def set_vol(dev, x):
    a = Addr(VMVC, OUT, MAIN); v = c_float(x)
    AT.AudioHardwareServiceSetPropertyData(dev, byref(a), 0, None, 4, byref(v))

Listener = CFUNCTYPE(c_int32, c_uint32, c_uint32, POINTER(Addr), c_void_p)
@Listener
def _on_change(obj, n, addrs, ctx):
    bridge.volumeChanged.emit(obj, get_vol(obj))   # Qt signal -> main thread
    return 0

dev = find("CMF Buds")
for elem in (0, 1, 2):                              # main + per-channel; dedupe in handler
    a = Addr(VOLM, OUT, elem)
    if CA.AudioObjectHasProperty(dev, byref(a)):
        CA.AudioObjectAddPropertyListener(dev, byref(a), _on_change, None)
AT.AudioHardwareServiceAddPropertyListener(dev, byref(Addr(VMVC, OUT, MAIN)), _on_change, None)
```
(Set `restype = c_int32` on these functions and check every OSStatus.)

Sources: Apple Core Audio functions index https://developer.apple.com/documentation/coreaudio/core-audio-functions ; PyObjC CoreAudio notes https://pyobjc.readthedocs.io/en/latest/apinotes/CoreAudio.html

---

## 2. Presses: MPRemoteCommandCenter + MPNowPlayingInfoCenter

### API
- `MediaPlayer.framework`: `MPRemoteCommandCenter.sharedCommandCenter()` and `MPNowPlayingInfoCenter.defaultCenter()`. Available since macOS 10.12.2. [doc] https://developer.apple.com/documentation/mediaplayer/mpremotecommandcenter
- Commands to register: `togglePlayPauseCommand`, `playCommand`, `pauseCommand`, `nextTrackCommand`, `previousTrackCommand`. Optionally `changePlaybackPositionCommand`, `skipForward/BackwardCommand`. Handlers are added with `addTargetWithHandler_(block)` and return `MPRemoteCommandHandlerStatusSuccess` (0). A command with no target is treated as disabled.
- **On macOS you must set `MPNowPlayingInfoCenter.defaultCenter().setPlaybackState_(MPNowPlayingPlaybackStatePlaying)` explicitly.** Unlike iOS, macOS does not infer the state from the audio session (Apple forums, accepted answer: https://developer.apple.com/forums/thread/685333). Also set `nowPlayingInfo` with at least a title (`MPMediaItemPropertyTitle`). [src] https://developer.apple.com/documentation/mediaplayer/mpnowplayinginfocenter (see "Setting the playback state in macOS")

### Which commands arrive for AVRCP from headsets
- **[belief]** Headset AVRCP passthrough PLAY / PAUSE / NEXT / PREVIOUS are received by `bluetoothd`, handed to the media-remote stack (`rcd` / `mediaremoted`), and sent to the now-playing app as `MPRemoteCommand`s. Many headsets send separate PLAY and PAUSE opcodes rather than a toggle, and macOS may map them to `playCommand`/`pauseCommand` *or* to `togglePlayPauseCommand`. **Register all three and treat any of them as "single press".** Next maps to `nextTrackCommand` and previous to `previousTrackCommand`. Run test 2 to record what actually arrives.
- The buds may send their own PAUSE/PLAY when you take them out of or put them in your ear (wear detection). Those look like presses. Ignore play/pause events that follow a wear event within a short window, if this turns out to be a problem.
- When no app is "now playing", macOS (`rcd`) launches **Music.app** on play. This is a well-known annoyance (see the Catalyst thread above). Orbit staying now-playing prevents it.

### Bundle / run loop / audio requirements
- **Run loop:** handlers run on the main thread through the main dispatch queue. A PySide6 `QGuiApplication` on macOS runs the Cocoa event loop (`NSApplication`) underneath, so blocks dispatched to the main queue are serviced. No separate `NSApplication.run()` is needed. [belief]
- **App bundle:** **[spec, likely needed]** Now Playing keys its entries by app identity (bundle ID and name). A bare `python3` process may show up as "Python" or not register reliably. Ship Orbit as a real `.app` (py2app/PyInstaller) with `CFBundleIdentifier`. For development, run it from a minimal `.app` wrapper.
- **Playing actual audio:** the primary sources say `playbackState` is what makes the app now-playing on macOS. **[spec]** In practice, "most recent app that started playing audio and set playing state" decides who wins, and apps that only set the state without audio are reported to lose focus more easily (https://developer.apple.com/forums/thread/799691: playbackState not updating after losing audio focus). **Recommendation: mirror the Windows design.** Play silence through `AVAudioEngine` (an `AVAudioPlayerNode` looping a zero-filled `AVAudioPCMBuffer`) routed to the buds, *and* set playbackState=playing.
  - Silence keeps the A2DP stream open. That costs some bud battery, but it also keeps latency low because the link does not sleep.
- **Keyboard play/pause:** the same Apple thread reports that the keyboard Play key sometimes did not reach a non-Music app even when Control Center worked. Bluetooth AVRCP takes a different path, so this needs testing.

### Competition with Spotify / Music / browsers
- The last app to start playback (and set its state) becomes now-playing. When the user presses play in Spotify, Spotify takes now-playing and the buds' presses go to Spotify, not Orbit.
- Reclaim: watch for loss (our `playbackState` change, or the mediaremote-adapter stream described in section 4), then within about 100 ms set `playbackState = Playing` again, reset `nowPlayingInfo`, and restart the silent player node. **[spec]** Whether re-asserting state without a new audio start is enough on 14/15 must be tested. The forum thread 799691 suggests the system UI does not update until the focused app changes state, so a restart of the audio engine may be needed.
- Side effect: Control Center and the menu-bar Now Playing widget will show **Orbit** instead of the song. Put the real track's title and artwork (read through mediaremote-adapter) into Orbit's `nowPlayingInfo` to soften this.

### Sketch
```python
from MediaPlayer import (MPRemoteCommandCenter, MPNowPlayingInfoCenter,
    MPNowPlayingPlaybackStatePlaying, MPMediaItemPropertyTitle, MPRemoteCommandHandlerStatusSuccess)
from AVFoundation import AVAudioEngine, AVAudioPlayerNode, AVAudioPCMBuffer, AVAudioPlayerNodeBufferLoops

def setup_presses(on_press):            # call on the Qt main thread after QGuiApplication exists
    cc = MPRemoteCommandCenter.sharedCommandCenter()
    def mk(kind):
        def h(event):
            on_press(kind)               # already on main thread
            return MPRemoteCommandHandlerStatusSuccess
        return h
    for cmd, kind in ((cc.togglePlayPauseCommand(), "single"), (cc.playCommand(), "single"),
                      (cc.pauseCommand(), "single"), (cc.nextTrackCommand(), "double"),
                      (cc.previousTrackCommand(), "triple")):
        cmd.setEnabled_(True); cmd.addTargetWithHandler_(mk(kind))
    np = MPNowPlayingInfoCenter.defaultCenter()
    np.setNowPlayingInfo_({MPMediaItemPropertyTitle: "Orbit"})
    np.setPlaybackState_(MPNowPlayingPlaybackStatePlaying)

def start_silence():
    eng = AVAudioEngine.alloc().init(); node = AVAudioPlayerNode.alloc().init()
    eng.attachNode_(node)
    fmt = eng.mainMixerNode().outputFormatForBus_(0)
    eng.connect_to_format_(node, eng.mainMixerNode(), fmt)
    buf = AVAudioPCMBuffer.alloc().initWithPCMFormat_frameCapacity_(fmt, 4800)
    buf.setFrameLength_(4800)            # zero-filled
    eng.startAndReturnError_(None); node.scheduleBuffer_atTime_options_completionHandler_(
        buf, None, AVAudioPlayerNodeBufferLoops, None); node.play()
    return eng, node                     # keep references alive
```
`AVAudioEngine` follows the system default output. If the buds are not the default output, set the output unit's `kAudioOutputUnitProperty_CurrentDevice` to the buds' AudioObjectID.

---

## 3. Hold: HFP `AT+BVRA=1`

What we know, sorted by confidence:
- **[doc, spec level]** HFP lets the HF (headset) send `AT+BVRA=1/0` to ask the AG (here, the Mac) to start or stop voice recognition. What the AG does beyond replying OK/ERROR is up to the implementation (HFP 1.6 spec text quoted in https://bugzilla.mozilla.org/show_bug.cgi?id=1182953; Google's guidance for accessories https://developers.google.com/assistant/accessories/integrate/bluetooth/voice-optimization).
- **[spec]** macOS behavior is undocumented. AirPods start Siri on a Mac through Apple's own AAP/AACP protocol, not BVRA. For third-party HFP headsets, there are reports in both directions (nothing happens / Siri opens), and none are authoritative. **Test 3 decides this.** If macOS ignores it or replies ERROR, the buds may stop sending it, or keep the toggle state confused.
- **[belief]** `bluetoothd` owns the HFP service-level connection to the headset. Public **IOBluetooth** HFP classes do not give a third-party app the AT stream of a headset already connected to macOS:
  - `IOBluetoothHandsFreeDevice` = **Mac acting as the headset** (talking to a phone). Wrong role.
  - `IOBluetoothHandsFreeAudioGateway` = Mac acting as the AG for a device. It needs its own RFCOMM channel and service record, and conflicts with the system's HFP AG. Unlikely to work while macOS's own connection is up. https://developer.apple.com/documentation/iobluetooth/iobluetoothhandsfreeaudiogateway
  - Both classes are old (10.7), barely maintained, and need the Bluetooth TCC permission (`NSBluetoothAlwaysUsageDescription`).
- **Ways to observe it:**
  1. **Unified log [spec]:** `log stream --level debug --predicate 'process == "bluetoothd" OR subsystem == "com.apple.bluetooth"'`, then grep for `BVRA`, `VoiceRecognition`, `HFP`. bluetoothd logs HFP AT traffic at debug level in some releases. Payloads may be shown as `<private>`. Revealing them needs a logging configuration profile, which is not something to ship. Reading `log stream` needs no TCC permission, but parsing log text is fragile across OS updates. Fine as an *experiment*, risky as a product feature.
  2. **PacketLogger** (Additional Tools for Xcode, https://developer.apple.com/download/all/?q=Additional%20Tools) **[doc/belief]** captures HCI traffic, including the RFCOMM AT commands. This is the right tool to *verify* what the buds send. It is not usable at runtime in a shipped app.
  3. **Side effects [spec]:** if macOS accepts BVRA it might open SCO (switch the buds to HFP). That would show up in CoreAudio as `kAudioDevicePropertyDeviceIsRunningSomewhere` on the buds' *input* device, a sample-rate change, or a default-input change, all observable without permissions. Check this during test 3.
  4. Private frameworks (`BluetoothManager`, `MobileBluetooth`, `CoreBluetooth` private XPC): unexplored, needs entitlements. Not recommended.
- **Conclusion:** treat hold as **unavailable on macOS by default**. Design the macOS gesture map so it works with rotate + single/double/triple only. Add a hold path later only if test 3 turns up a reliable signal (most likely a log-stream match or an audio side effect).

---

## 4. Output actions

### 4a. Keyboard combos: Quartz Event Services
- `CGEventCreateKeyboardEvent(source, CGKeyCode, keyDown)`, `CGEventSetFlags(ev, kCGEventFlagMaskCommand | ...)`, `CGEventPost(kCGHIDEventTap, ev)`. Key codes are `kVK_*` from `HIToolbox/Events.h` (layout-dependent for letters: `kVK_ANSI_*` are physical positions). [doc] https://developer.apple.com/documentation/coregraphics/1456564-cgeventcreatekeyboardevent
- Use `CGEventSourceCreate(kCGEventSourceStateHIDSystemState)` as the source so modifier state behaves correctly. Post both modifier keydown/keyup events *and* set flags on the main key, because some apps check one and some check the other.
- Permission: **Accessibility**. Posting without it fails silently: no error, events are dropped. Check with `AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})`, which shows the system prompt (https://developer.apple.com/documentation/applicationservices/1459186-axisprocesstrustedwithoptions). macOS 10.15+ also has `CGPreflightPostEventAccess()` / `CGRequestPostEventAccess()` for exactly "post events". [doc]
- Pitfalls: TCC grants are tied to the code-signing identity. An unsigned or ad-hoc re-signed build loses the grant on every rebuild, and running from Terminal grants Terminal instead. Secure Input (password fields, some terminals) blocks synthetic keys.

```python
from Quartz import (CGEventCreateKeyboardEvent, CGEventSetFlags, CGEventPost, kCGHIDEventTap,
    kCGEventFlagMaskCommand, CGEventSourceCreate, kCGEventSourceStateHIDSystemState)
SRC = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
def tap(keycode, flags=0):
    for down in (True, False):
        e = CGEventCreateKeyboardEvent(SRC, keycode, down); CGEventSetFlags(e, flags)
        CGEventPost(kCGHIDEventTap, e)
tap(0x06, kCGEventFlagMaskCommand)   # Cmd+Z (kVK_ANSI_Z = 0x06)
```

### 4b. Smooth scrolling
- `CGEventCreateScrollWheelEvent(source, kCGScrollEventUnitPixel, wheelCount, dy[, dx])` is variadic. PyObjC exposes it. macOS 13+ also has the non-variadic `CGEventCreateScrollWheelEvent2(source, units, wheelCount, w1, w2, w3)`, which is easier to bind. [doc] https://developer.apple.com/documentation/coregraphics/1541327-cgeventcreatescrollwheelevent
- For trackpad-like smoothness: emit many small pixel deltas from a 120 Hz `QTimer` with easing, and set `CGEventSetIntegerValueField(e, kCGScrollWheelEventIsContinuous, 1)`. Optionally set `kCGScrollWheelEventScrollPhase` (began/changed/ended) so apps such as Safari treat it as a gesture. Without phases some apps add their own acceleration or snap. [belief]
- **Scroll events go to the window under the mouse pointer, not to the focused window.** The overlay must ignore mouse events (section 5), or the scroll lands on the overlay. Posting scroll events needs Accessibility, the same as keys.
- Respect the user's "natural scrolling" setting? Synthetic events are *not* inverted by the system [belief]. Read `com.apple.swipescrolldirection` if we want to match it.

```python
from Quartz import (CGEventCreateScrollWheelEvent, kCGScrollEventUnitPixel, CGEventSetIntegerValueField,
    kCGScrollWheelEventIsContinuous, CGEventPost, kCGHIDEventTap)
def scroll_px(dy, dx=0):
    e = CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitPixel, 2, int(dy), int(dx))
    CGEventSetIntegerValueField(e, kCGScrollWheelEventIsContinuous, 1)
    CGEventPost(kCGHIDEventTap, e)
```

### 4c. Media forwarding to the real player
The core problem: **while Orbit is now-playing, every system media command, including synthesized media keys, comes back to Orbit.** Forwarding has to target the real player directly.

Options:
1. **AppleScript / Apple Events (public, recommended for Music and Spotify):**
   `tell application "Spotify" to playpause | next track | previous track` and the same verbs for `"Music"`. Use `NSAppleScript` (PyObjC) on a worker thread, or `osascript`. Needs **Automation TCC** per target app (prompt "Orbit wants to control Spotify"), and `NSAppleEventsUsageDescription` in Info.plist. Browsers (Chrome/Safari video) have no clean verb for this.
2. **MediaRemote private framework (`MRMediaRemoteSendCommand(kMRTogglePlayPause=2, NULL)`, `MRMediaRemoteSendCommandToApp`):** https://theapplewiki.com/wiki/Dev:MediaRemote.framework
   - **Since macOS 15.4, MediaRemote is non-functional when loaded directly by non-Apple processes.** mediaremoted checks for a `com.apple.*` bundle ID or an entitlement ("completely non-functional when being loaded directly from within an app, starting with macOS 15.4", https://github.com/ungive/mediaremote-adapter; also https://forum.keyboardmaestro.com/t/beware-upgrading-to-macos-15-4-if-you-need-now-playing-data/40285). The documented breakage is clearly the *read* path. Whether *send* still works directly is unconfirmed, so assume not.
   - Workaround: **mediaremote-adapter** runs a helper framework inside `/usr/bin/perl` (which reports as `com.apple.perl`). It supports `stream` (now-playing changes), `get` and `send <id>` (0=play, 1=pause, 2=toggle, 4=next, 5=previous). This is the best way to (a) **know which app was now-playing before Orbit took over** and (b) read track metadata. But `send` goes to *the current now-playing app*, which is Orbit. This relies on Apple not closing the hole (BSD-3 licensed, actively maintained).
3. **NX system-defined media key events:** `NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(NSEventTypeSystemDefined=14, (0,0), 0xa00 if down else 0xb00, 0, 0, None, 8, (key<<16)|((0xa if down else 0xb)<<8), -1)`, then `CGEventPost(kCGHIDEventTap, ev.CGEvent())`. Keys: `NX_KEYTYPE_PLAY=16, NEXT=17, PREVIOUS=18, SOUND_UP=0, SOUND_DOWN=1, BRIGHTNESS_UP=2, BRIGHTNESS_DOWN=3, MUTE=7` (IOKit `ev_keymap.h`). [src: widely used, e.g. in Hammerspoon `hs.eventtap.event.newSystemKeyEvent`] Needs Accessibility. **They route to the now-playing app (Orbit)**, so they only help after Orbit gives up now-playing.
4. **"Release-and-send" pattern [spec]:** stop the silent player, set `playbackState = Stopped`, wait about 150-300 ms for MediaRemote to fall back to the previous app, post the NX key, then reclaim now-playing. This works for any player (browsers too) but is racy, and it may leave the system's choice of player unpredictable. Prototype it after the AppleScript path works.

**Recommendation:** AppleScript for Music and Spotify. Use mediaremote-adapter `stream` to remember the last real player's bundle ID. Fall back to release-and-send for other apps.

### 4d. Brightness
- **Built-in display (Apple Silicon):** private `DisplayServices.framework`, `int DisplayServicesSetBrightness(CGDirectDisplayID, float)` / `DisplayServicesGetBrightness(id, float*)`. MonitorControl uses it for Apple and built-in displays, and Studio Display / Pro Display XDR use the same call [src] (https://github.com/MonitorControl/MonitorControl). Call through ctypes on `/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices`. Older `CoreDisplay_Display_SetUserBrightness` also exists. No TCC permission is needed. The system HUD does not appear (which is fine, we draw our own). Find the built-in display with `CGDisplayIsBuiltin`.
- **Alternative, simple, public-ish:** post NX `BRIGHTNESS_UP/DOWN` system-defined keys (section 4c). This shows the system HUD, steps in 1/16 increments, and affects only the built-in or Apple displays. It does not loop back to Orbit because brightness keys do not route through now-playing.
- **External DDC/CI monitors on Apple Silicon:** private `IOAVService` (`IOAVServiceCreateWithService`, `IOAVServiceWriteI2C`, VCP 0x10 brightness). The old IOFramebuffer I2C path does not work on M1+ (https://alinpanaitiu.com/blog/journey-to-ddc-on-m1-macs/). The easiest route is to shell out to **m1ddc** (`m1ddc display 1 set luminance 60`, https://github.com/waydabber/m1ddc), or port its ~200 lines to ctypes. Limits: the built-in HDMI port on some M1/M2 machines, DisplayLink and many docks block DDC. DDC writes are slow (~50 ms) and some monitors misbehave if written to quickly, so coalesce writes to at most about 5-10 Hz.
- Fallback for monitors without DDC: gamma dimming (`CGSetDisplayTransferByFormula`). This is software-only and looks worse.

### 4e. App switching
- **Synthesize Cmd+Tab with Cmd held:** post Cmd keydown, then Tab (and Shift+Tab for reverse) on each rotation step, and Cmd keyup on press or timeout. This shows the real system app switcher and matches the Windows Alt+Tab behavior. Needs Accessibility. [belief, widely used by macro tools] Pitfall: if Orbit crashes while Cmd is "held", the modifier sticks. Always release Cmd in a `finally` block and an `atexit` hook.
- **Own switcher alternative:** `NSWorkspace.sharedWorkspace().runningApplications()` filtered to `activationPolicy == Regular`, with icons in Orbit's overlay, then `app.activateWithOptions_(...)`. Caution: macOS 14 introduced *cooperative activation*. `activateIgnoringOtherApps` is deprecated, and an app that is not active may not be allowed to activate another app (https://developer.apple.com/documentation/appkit/nsapplication/4168326-yieldactivation). Synthesizing Cmd+Tab avoids this. Window-level (not app-level) switching needs the Accessibility API (`AXUIElement` windows + `AXRaise`).

### 4f. Launching apps
`NSWorkspace.sharedWorkspace().openApplicationAtURL_configuration_completionHandler_(url, NSWorkspaceOpenConfiguration.configuration(), None)`, or `open -b <bundleid>`. No permissions needed.

---

## 5. Overlay: Qt Quick window above full-screen apps, non-activating, click-through

- Qt side: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput`, a transparent `QQuickWindow` (`setColor(Qt.transparent)`). `Qt.Tool` makes Qt create an **NSPanel**.
- Reaching the NSWindow: on Cocoa, `QWindow.winId()` is an **NSView\***, not an NSWindow. Qt developer's explanation: https://lists.qt-project.org/pipermail/interest/2014-January/010489.html. Wrap it with `objc.objc_object(c_void_p=int(win.winId()))`, then call `.window()`. Call this only after the window is created (`win.create()` or after `show()`).
- NSWindow settings (AppKit) [doc]:
  - `setLevel_(NSStatusWindowLevel)` (25) or `NSPopUpMenuWindowLevel` (101). These sit above full-screen app windows when combined with the collection behavior below. Avoid `NSScreenSaverWindowLevel` (it covers the system switcher and menus).
  - `setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorStationary | NSWindowCollectionBehaviorIgnoresCycle)`. https://developer.apple.com/documentation/appkit/nswindow/collectionbehavior-swift.property
  - `setIgnoresMouseEvents_(True)` for click-through (`WindowTransparentForInput` does this too, but set it explicitly).
  - `setHidesOnDeactivate_(False)`. **Pitfall:** NSPanels created by Qt::Tool hide when the app deactivates, and an LSUIElement agent is almost never active.
  - `setCanHide_(False)`, `setHasShadow_(False)`, `setOpaque_(False)`.
  - Show with `nswin.orderFrontRegardless()` rather than letting Qt call `makeKeyAndOrderFront`, which would activate Orbit and steal focus from the user's app.
- **Full-screen spaces:** only windows of a **UIElement/accessory app** (LSUIElement=1, or `NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)`) with `FullScreenAuxiliary` reliably appear over another app's full-screen space. A regular app's window pulls the user back to the desktop space. [belief, widely reported]
- Non-activating style: `NSWindowStyleMaskNonactivatingPanel` only fully takes effect if set when the panel is created. Changing it afterwards is a known AppKit quirk (the WindowServer tag does not update). With ignoresMouseEvents=True and no clicks, this does not matter.
- Multiple monitors: position the overlay on the screen under the mouse (`NSEvent.mouseLocation()` + `QGuiApplication.screenAt`).
- Apply these settings again after every Qt `show()` or `setFlags()` call, because Qt may recreate or reconfigure the NSWindow.

```python
import objc
from AppKit import (NSStatusWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary, NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorIgnoresCycle)
def macify(qwindow):
    view = objc.objc_object(c_void_p=int(qwindow.winId()))
    w = view.window()
    w.setLevel_(NSStatusWindowLevel)
    w.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces |
        NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorStationary |
        NSWindowCollectionBehaviorIgnoresCycle)
    w.setIgnoresMouseEvents_(True); w.setHidesOnDeactivate_(False)
    w.setOpaque_(False); w.setHasShadow_(False)
    w.orderFrontRegardless()
```

---

## 6. Packaging, permissions, launch at login

- **Bundle:** build a `.app` with py2app or PyInstaller (`--windowed`, `--osx-bundle-identifier`). Info.plist:
  - `LSUIElement = true`: no Dock icon or menu bar, and it allows the overlay over full-screen apps. Add a menu-bar `NSStatusItem` (or `QSystemTrayIcon`) for settings and quit.
  - `NSAppleEventsUsageDescription` (for AppleScript to Music/Spotify).
  - `LSMinimumSystemVersion = 13.0`.
- **Signing:** sign with a Developer ID, hardened runtime, and notarize. Hardened runtime needs `com.apple.security.automation.apple-events` for Apple Events. ctypes/PyObjC loading private frameworks works under the hardened runtime if `com.apple.security.cs.disable-library-validation` is set (PyInstaller bundles usually need it). A stable signature keeps TCC grants across updates. Ad-hoc builds re-prompt every rebuild.
- **TCC prompts Orbit needs:**
  | Permission | Why | How triggered |
  |---|---|---|
  | Accessibility | CGEventPost (keys, scroll, Cmd+Tab, NX media/brightness keys) | `AXIsProcessTrustedWithOptions(prompt)`; user toggles in Settings > Privacy & Security > Accessibility; Orbit may need a relaunch |
  | Automation (per app) | AppleScript to Spotify/Music | first Apple Event to each app |
  | *Not needed:* Microphone | we never open the buds' input; playing silence is output only | — |
  | *Not needed:* Input Monitoring | only for CGEventTap *listening* to keys, which we don't do | — |
  | *Not needed:* Bluetooth | only if we use IOBluetooth/CoreBluetooth (section 3 experiments) | `NSBluetoothAlwaysUsageDescription` |
  | *Not needed:* Screen Recording | — | — |
- **Launch at login:** `SMAppService.mainAppService().registerAndReturnError_(None)` (ServiceManagement, macOS 13+). It shows up in Settings > General > Login Items and the user can turn it off there. Check `.status()`. https://developer.apple.com/documentation/servicemanagement/smappservice . Alternative: a LaunchAgent plist in `~/Library/LaunchAgents` (older approach, shows a "background item added" notification on 13+).
- Bundle **m1ddc** and **mediaremote-adapter** (perl script + framework) inside `Contents/Resources` and sign them.

---

## Test checklist (first session on a Mac with the buds)
1. Rotation: run the ctypes listener. Do 'vmvc' and 'volm' fire per click? What delta? Does the HUD flash? Does restoring cause an echo and a buds-side rate-limit hit?
2. Presses: run as a bundled `.app` and as bare python. Which MPRemoteCommands arrive for single/double/triple? Does it work with and without the silent AVAudioEngine? What happens when Spotify starts playing?
3. Hold: run PacketLogger plus `log stream` (bluetoothd, debug level) while holding. Is AT+BVRA sent? What does the Mac reply? Does Siri open? Any CoreAudio side effect on the buds' input device?
4. MediaRemote on 15.x: does `MRMediaRemoteSendCommand` called directly from Orbit do anything? Does mediaremote-adapter `stream` report the previous player?
5. Overlay over a full-screen Safari video and over a full-screen Keynote presentation.

---

## Recommended design

1. **Process model:** one PySide6 `.app`, LSUIElement agent, Developer-ID signed. Qt's main loop is the Cocoa run loop, so MediaPlayer blocks and AppKit calls run on the Qt main thread. CoreAudio callbacks arrive on the HAL thread and are forwarded with Qt signals.
2. **`MacDialSource` (input):**
   - Rotation: ctypes CoreAudio listener on the buds' `VirtualMainVolume` (plus per-channel 'volm' as a backup), with the device found by Bluetooth transport type + name/UID and re-resolved on device-list changes. Turn the delta into steps (`round(Δ/step)`), then restore the volume through `AudioHardwareServiceSetPropertyData`, with echo suppression. Accept the possible system HUD flash.
   - Presses: `MPRemoteCommandCenter` (toggle/play/pause → single, next → double, previous → triple), `playbackState=Playing` + a silent `AVAudioEngine` loop routed to the buds. A reclaim loop runs when another app takes now-playing.
   - Hold: **not supported in v1 on macOS.** The gesture map must not depend on it (for example, use triple press to open the menu on Mac). Prototype log-stream/side-effect detection separately.
3. **`MacActions` (output):** Quartz `CGEventPost` for keys, pixel/continuous scroll and held-Cmd+Tab switching. AppleScript forwarding to Music/Spotify, with mediaremote-adapter tracking the last real player and release-and-send for other apps. DisplayServices for built-in brightness, bundled m1ddc for external monitors. NSWorkspace for launching apps.
4. **`MacOverlay`:** the existing Qt Quick wheel, made frameless and transparent, with the NSWindow patched through PyObjC (status level, all spaces + full-screen auxiliary, ignores mouse, no hide on deactivate, `orderFrontRegardless`).
5. **Onboarding:** first run checks `AXIsProcessTrusted` and walks the user to the Accessibility pane. It requests Automation lazily, and registers the login item with `SMAppService`.

### Biggest risks
1. **Hold gesture likely unusable on macOS.** No public API exposes the headset's HFP AT commands, and what macOS does with `AT+BVRA` is unknown (it may even open Siri).
2. **Now-playing ownership is fragile.** macOS's choice of now-playing app is undocumented. Reclaiming from Spotify/browsers may need audio restarts, and Orbit replaces the real track in Control Center.
3. **Media forwarding:** MediaRemote is locked down from 15.4. The adapter depends on a Perl-entitlement loophole Apple could close, synthesized media keys loop back to Orbit, and AppleScript covers only scriptable players.
4. **Rotation feedback:** AVRCP volume → CoreAudio volume is highly likely but unverified for these buds. The system volume HUD may flash on every click with no supported way to hide it, and the restore echo may interact with the buds' rate limit.
5. **Private APIs** (DisplayServices, IOAVService/m1ddc, MediaRemote) can break with any macOS update. **TCC friction**: everything that posts events depends on Accessibility being granted to a stably signed bundle.
