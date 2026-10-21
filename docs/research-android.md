# Orbit on Android: research notes

Goal: a native Android app (Kotlin, minSdk 26, targetSdk 35) that turns the CMF Buds Pro 2 case dial into a Surface-Dial-style controller, the same way the Windows build does:

| Dial gesture | What reaches the phone | Android entry point (verified in AOSP source) |
|---|---|---|
| Rotate | AVRCP absolute-volume change | `AvrcpVolumeManager.setVolume()` calls `AudioManager.setStreamVolume(STREAM_MUSIC, ...)` |
| Single / double / triple press | AVRCP passthrough PLAY or PAUSE / FORWARD / BACKWARD | `AvrcpTargetService.sendMediaKeyEvent()` calls `AudioManager.dispatchMediaKeyEvent()` and goes to the media-button session |
| Press and hold | HFP `AT+BVRA=1` | `HeadsetService.startVoiceRecognitionByHeadset()` starts an `Intent.ACTION_VOICE_COMMAND` activity |

"Verified in AOSP" means I read the current `main` branch of `packages/modules/Bluetooth` and `frameworks/base`. Phone makers (Samsung, Xiaomi, OnePlus and so on) can change this code, so every point marked **[test on device]** needs checking on the target phone.

Source files read (raw `?format=TEXT` from android.googlesource.com, `refs/heads/main`):
- AvrcpVolumeManager.java: https://android.googlesource.com/platform/packages/modules/Bluetooth/+/refs/heads/main/android/app/src/com/android/bluetooth/avrcp/AvrcpVolumeManager.java
- AvrcpTargetService.java: https://android.googlesource.com/platform/packages/modules/Bluetooth/+/refs/heads/main/android/app/src/com/android/bluetooth/avrcp/AvrcpTargetService.java
- HeadsetSystemInterface.java: https://android.googlesource.com/platform/packages/modules/Bluetooth/+/refs/heads/main/android/app/src/com/android/bluetooth/hfp/HeadsetSystemInterface.java
- HeadsetService.java / HeadsetStateMachine.java (same folder, `hfp/`)
- AudioService.java: https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/core/java/com/android/server/audio/AudioService.java
- roles.xml (role definitions): https://android.googlesource.com/platform/packages/modules/Permission/+/refs/heads/main/PermissionController/res/xml/roles.xml
- AccessibilityService.java: https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/accessibilityservice/AccessibilityService.java

---

## 1. Rotation (absolute volume)

### What actually happens
When the buds report a new volume, the Bluetooth app runs this (AvrcpVolumeManager, `setVolume`):

```java
mAudioManager.setStreamVolume(
        AudioManager.STREAM_MUSIC,
        deviceVolume,
        (deviceVolume != getVolume(device, -1) ? AudioManager.FLAG_SHOW_UI : 0)
                | AudioManager.FLAG_BLUETOOTH_ABS_VOLUME);
```

What this means for Orbit:
- **It is a direct `setStreamVolume` call, not a volume key.** MediaSession volume routing (`setPlaybackToRemote` + `VolumeProvider`) only handles volume *key* events (`dispatchVolumeKeyEvent` / `adjustSuggestedStreamVolume`). A direct `setStreamVolume` goes straight to `AudioService`. **So a `VolumeProviderCompat` session cannot intercept the dial. The real STREAM_MUSIC volume always changes, and Orbit has to restore it.** Docs: https://developer.android.com/reference/android/media/session/MediaSession#setPlaybackToRemote(android.media.VolumeProvider)
- **The system volume panel will appear** (`FLAG_SHOW_UI`) whenever the new value differs from the stored per-device value. When Orbit restores the volume, the stack stores the restored value (`sendVolumeChanged` → `storeVolumeForDevice`), so *every* click shows the panel. A normal app has no supported way to hide it: `VolumePolicy`/`VolumeController` are system-only, and the panel window (`TYPE_VOLUME_OVERLAY`) sits above app overlays. Ways to live with it: (a) accept it; (b) let the user pick a small or minimal volume-panel style where the OEM offers one (Samsung "Sound Assistant" and similar); (c) with root/Shizuku, swap in a custom volume controller. **This is the biggest UX gap compared with Windows.**
- One dial click is often **not** exactly one Android step. AVRCP volume is 0–127, STREAM_MUSIC usually has 15 steps (some OEMs 25–30), and `avrcpToSystemVolume` rounds. A click can come out as +1, +2 or 0 steps, and 0 sends no broadcast. **[test on device]**: log raw values for 20 clicks each way. If clicks get lost, pick a baseline where the buds' step size lines up with the phone's.
- If the stream is already at max (or 0), turning further makes no change and Android sends no event. Like on Windows, keep a **mid-range baseline** (for example max/2) and restore to it after each click.
- When Orbit restores, `AudioService` → `AvrcpVolumeManager.sendVolumeChanged` sends `SetAbsoluteVolume` back to the buds, so their internal level re-syncs and the next click counts up or down from the baseline.

### How to detect the change

| Option | Status | Notes |
|---|---|---|
| `"android.media.VOLUME_CHANGED_ACTION"` broadcast | Hidden (`@UnsupportedAppUsage`), but still sent in `main` | **Best choice.** Extras: `android.media.EXTRA_VOLUME_STREAM_TYPE`, `android.media.EXTRA_VOLUME_STREAM_VALUE`, `android.media.EXTRA_PREV_VOLUME_STREAM_VALUE`. Sent immediately from `VolumeStreamState.setIndex`. |
| `ContentObserver` on `Settings.System` (`volume_music_bt_a2dp`, `volume_music_ble_headset`, ...) | Works, but not intended for this | `AudioService` saves volume with `PERSIST_DELAY = 500 ms` (debounced), so it is **slow and merges several clicks into one**. Use only as a fallback or cross-check. |
| `AudioManager` callbacks | None public | `registerVolumeGroupCallback` is `@SystemApi`. `AudioPlaybackCallback` reports playback, not volume. |
| Polling `getStreamVolume(STREAM_MUSIC)` | Works | 30–50 ms polling while the wheel is open is a reasonable backup, but it costs battery when used all the time. |

Things to watch with the broadcast (from `AudioService`):
- Sent with `FLAG_RECEIVER_REGISTERED_ONLY_BEFORE_BOOT`, so **only runtime-registered receivers get it**. A manifest receiver gets nothing. Register it in the foreground service.
- `DELIVERY_GROUP_POLICY_MOST_RECENT` keyed by stream: **queued broadcasts are merged and only the latest is delivered**. Don't sum `value - prev` per intent. Use `value - baseline`, where `baseline` is the value Orbit last set.
- `DEFERRAL_POLICY_UNTIL_ACTIVE`: delivery is held back while the process is cached or frozen. A running foreground service avoids this.
- Orbit's own restore also fires the broadcast. Ignore events where `value == baseline`.
- Android 14 (API 34) needs `RECEIVER_EXPORTED`/`RECEIVER_NOT_EXPORTED` for runtime receivers, *except* for receivers that only listen to system broadcasts. Passing `ContextCompat.RECEIVER_NOT_EXPORTED` is fine because system broadcasts still arrive. https://developer.android.com/about/versions/14/behavior-changes-14#runtime-receivers-exported

### Restore without UI
`audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, baseline, 0)`. Flags `0` means no panel from *our* call (the BT stack's own call has already shown it). No permission is needed. In Do Not Disturb, STREAM_MUSIC changes are still allowed, while ring/notification streams would need `ACCESS_NOTIFICATION_POLICY`. https://developer.android.com/reference/android/media/AudioManager#setStreamVolume(int,%20int,%20int)

### Idea to test: turn off absolute volume
In Developer options → "Disable absolute volume", the phone doesn't negotiate absolute volume. Some buds then send AVRCP passthrough VOLUME_UP/DOWN instead. *If* the CMF buds do that, and the keys reach `MediaSessionService.dispatchVolumeKeyEvent`, a session with `setPlaybackToRemote(VolumeProvider)` **would** catch them, the real volume would never change, and the panel would show Orbit's remote-volume slider instead. **[test on device]**: this changes a global developer setting the user would have to flip, and buds firmware may just stop sending anything. (Side effect of a remote-volume session: while it is the active session, the phone's own volume keys control it too.)

### Kotlin sketch
```kotlin
class RotationDetector(
    private val ctx: Context,
    private val onTicks: (Int) -> Unit,
) {
    private val am = ctx.getSystemService(AudioManager::class.java)
    private val stream = AudioManager.STREAM_MUSIC
    var baseline = am.getStreamMaxVolume(stream) / 2
        private set
    private var lastRestore = 0L

    private val rx = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            if (i.getIntExtra("android.media.EXTRA_VOLUME_STREAM_TYPE", -1) != stream) return
            val v = i.getIntExtra("android.media.EXTRA_VOLUME_STREAM_VALUE", -1)
            if (v < 0 || v == baseline) return            // our own restore, or merged no-op
            val delta = v - baseline                       // not v - prev: broadcasts merge
            am.setStreamVolume(stream, baseline, 0)         // swallow, no UI from us
            onTicks(delta)
        }
    }

    fun start() {
        am.setStreamVolume(stream, baseline, 0)
        ContextCompat.registerReceiver(
            ctx, rx, IntentFilter("android.media.VOLUME_CHANGED_ACTION"),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
    }
    fun stop() = ctx.unregisterReceiver(rx)

    /** Volume tool: let the change through and move the baseline. */
    fun acceptAsRealVolume(newValue: Int) { baseline = newValue.coerceIn(1, am.getStreamMaxVolume(stream) - 1) }
}
```
Only treat the event as a dial click when the active output is the buds (`am.getDevices(GET_DEVICES_OUTPUTS)` / `AudioDeviceCallback`, type `TYPE_BLUETOOTH_A2DP` or `TYPE_BLE_HEADSET`). Otherwise the phone's own volume keys would be swallowed too. You can also check `KeyEvent` volume keys from the AccessibilityService (`onKeyEvent` with `FLAG_REQUEST_FILTER_KEY_EVENTS`): a phone key press passes through it, an AVRCP change doesn't. That's a clean way to tell them apart.

---

## 2. Presses (media buttons)

### Routing on Android 8+
From the docs (https://developer.android.com/media/legacy/media-buttons): *"the system tries to find the last app with a MediaSession that played audio locally. If the session is still active Android sends the event directly to it."* If the session is inactive it falls back to that app's media-button receiver, and otherwise the event is dropped.

AVRCP passthrough uses the same route: `AvrcpTargetService.sendMediaKeyEvent` builds a `KeyEvent` and calls `mAudioManager.dispatchMediaKeyEvent(event)` → `MediaSessionService` → media-button session. It does **not** go through the input pipeline, so `AccessibilityService.onKeyEvent` does **not** see buds presses. Being the media-button session is the only way in.

One catch in `sendMediaKeyEvent` (behind the `setAddressedPlayer` flag): a `KEYCODE_MEDIA_PLAY` is sent to the AVRCP *addressed player* via `playCurrent()` when that differs from the active player. Keep Orbit the addressed/active player (it will be while it is the playing session). **[test on device]**

### What the buds send
- Single press: AVRCP PLAY or PAUSE. Buds choose based on the playback status the phone last reported, so with Orbit always "PLAYING" expect `KEYCODE_MEDIA_PAUSE` (127). Also handle `KEYCODE_MEDIA_PLAY` (126), `KEYCODE_MEDIA_PLAY_PAUSE` (85) and `KEYCODE_HEADSETHOOK` (79) as "press".
- Double press: FORWARD → `KEYCODE_MEDIA_NEXT` (87).
- Triple press: BACKWARD → `KEYCODE_MEDIA_PREVIOUS` (88).
- **Never actually go to PAUSED** when you get a pause. Keep `PlaybackState.STATE_PLAYING`, or the buds start sending PLAY and you run into the addressed-player path above.
- Use `ACTION_DOWN` only (each press arrives as DOWN+UP).

### Keeping the media-button role
1. A **foreground service** with `foregroundServiceType="mediaPlayback"`. Android 14+ also needs `FOREGROUND_SERVICE_MEDIA_PLAYBACK`. https://developer.android.com/develop/background-work/services/fgs/service-types#media
2. An active `MediaSession` with `PlaybackState.STATE_PLAYING` and actions PLAY|PAUSE|PLAY_PAUSE|SKIP_TO_NEXT|SKIP_TO_PREVIOUS.
3. **Actually playing audio** locally: an `AudioTrack` streaming zeros with `USAGE_MEDIA`/`CONTENT_TYPE_MUSIC`. "Played audio locally" comes from `AudioPlaybackConfiguration`, so a session alone is not enough.
4. **Do not request audio focus.** Without focus Orbit's silence mixes alongside real music and never pauses the user's player. (Android 15 also only allows `requestAudioFocus` from the top app or an FGS: https://developer.android.com/about/versions/15/behavior-changes-15)
5. **Other players take over:** when Spotify or YouTube starts or resumes, it becomes the "last app that played audio" and gets the next presses. Fix: watch `AudioManager.registerAudioPlaybackCallback` (public, API 26). When another player becomes active, `stop()`+`play()` the silent `AudioTrack` (and re-`setActive(true)`) so Orbit is the most recent player again. Then forward single presses to the real player (below). **[test on device]**: OEM routing can differ, so check with `adb shell dumpsys media_session` ("Media button session is ...").
6. Use the framework `android.media.session.MediaSession` (not deprecated, gives raw `onMediaButtonEvent`) or `MediaSessionCompat`. Media3's `MediaSession` needs a `Player` and hides raw key handling, so it's overkill here. Call `setMediaButtonReceiver(null)` (or the API 31 `setMediaButtonBroadcastReceiver(null)`) so Android doesn't relaunch Orbit after it has been stopped.

Side effects to tell the user about:
- Orbit shows as the "now playing" media card in quick settings and on the lock screen (Android 11+ media controls). Give it sensible metadata ("Orbit — dial active").
- Streaming silence keeps the A2DP link and the audio DSP active, which costs some battery on phone and buds. Consider stopping the silence when the screen is off (and losing presses then) as a user setting.
- Android 13+ `POST_NOTIFICATIONS`: notifications tied to a media session are exempt, but ask anyway for the FGS notification. https://developer.android.com/develop/ui/views/notifications/notification-permission#exemptions

### Forwarding to the real player
- `NotificationListenerService` (user enables it in Settings → Notification access, `Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS`). That lets you call `MediaSessionManager.getActiveSessions(ComponentName(ctx, OrbitNotificationListener::class.java))` and `addOnActiveSessionsChangedListener`. https://developer.android.com/reference/android/media/session/MediaSessionManager#getActiveSessions(android.content.ComponentName)
- Pick the first controller whose `packageName != ourPackage` (the list is sorted by priority/recency), preferring one in `STATE_PLAYING`. Call `controller.transportControls.play()/pause()/skipToNext()/skipToPrevious()`, or `controller.dispatchMediaButtonEvent(KeyEvent)` to pass the exact key through.
- **Do not** use `AudioManager.dispatchMediaKeyEvent` to forward: it would route straight back to Orbit.
- After forwarding PLAY to a paused player, that player starts audio and becomes the button session, so re-assert Orbit (step 5).

### Kotlin sketch
```kotlin
class OrbitMediaService : Service() {
    private lateinit var session: MediaSession
    private lateinit var silence: AudioTrack

    override fun onCreate() {
        super.onCreate()
        startForeground(1, buildNotification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
        session = MediaSession(this, "Orbit").apply {
            setCallback(object : MediaSession.Callback() {
                override fun onMediaButtonEvent(i: Intent): Boolean {
                    val ev = i.getParcelableExtra(Intent.EXTRA_KEY_EVENT, KeyEvent::class.java)  // API 33; use deprecated overload below
                        ?: return false
                    if (ev.action != KeyEvent.ACTION_DOWN) return true
                    when (ev.keyCode) {
                        KeyEvent.KEYCODE_MEDIA_PLAY, KeyEvent.KEYCODE_MEDIA_PAUSE,
                        KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, KeyEvent.KEYCODE_HEADSETHOOK -> Dial.press(1)
                        KeyEvent.KEYCODE_MEDIA_NEXT -> Dial.press(2)
                        KeyEvent.KEYCODE_MEDIA_PREVIOUS -> Dial.press(3)
                    }
                    return true // swallow; never change our PLAYING state
                }
            })
            setPlaybackState(PlaybackState.Builder()
                .setActions(PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or
                    PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_SKIP_TO_NEXT or
                    PlaybackState.ACTION_SKIP_TO_PREVIOUS)
                .setState(PlaybackState.STATE_PLAYING, 0, 1f).build())
            setMediaButtonReceiver(null)
            isActive = true
        }
        silence = AudioTrack.Builder()
            .setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
            .setAudioFormat(AudioFormat.Builder().setSampleRate(44100)
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
            .setTransferMode(AudioTrack.MODE_STATIC)
            .setBufferSizeInBytes(44100 * 2).build().apply {
                write(ShortArray(44100), 0, 44100)     // 1 s of zeros
                setLoopPoints(0, 44100, -1)            // loop forever
                play()
            }
        getSystemService(AudioManager::class.java).registerAudioPlaybackCallback(
            object : AudioManager.AudioPlaybackCallback() {
                override fun onPlaybackConfigChanged(cfgs: List<AudioPlaybackConfiguration>) {
                    if (cfgs.size > 1) reassert()       // someone else started playing
                }
            }, null)
    }

    private fun reassert() { silence.pause(); silence.flush(); silence.reloadStaticData(); silence.play(); session.isActive = true }
    override fun onBind(i: Intent?) = null
}
```
(For API < 33 use `@Suppress("DEPRECATION") i.getParcelableExtra<KeyEvent>(Intent.EXTRA_KEY_EVENT)`. Debounce `reassert()` so two silent apps can't fight in a loop.)

Manifest:
```xml
<uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK"/>
<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>
<service android:name=".OrbitMediaService" android:exported="false"
         android:foregroundServiceType="mediaPlayback"/>
<service android:name=".OrbitNotificationListener" android:exported="true"
         android:permission="android.permission.BIND_NOTIFICATION_LISTENER_SERVICE">
  <intent-filter><action android:name="android.service.notification.NotificationListenerService"/></intent-filter>
</service>
```

---

## 3. Hold (`AT+BVRA=1`)

### What Android does (verified)
`HeadsetStateMachine.processVrEvent(VR_STATE_STARTED)` → `HeadsetService.startVoiceRecognitionByHeadset(device)`. That function:
1. Refuses (sends `ERROR` to the buds) if a call or SCO audio is active, or if an earlier VR request is still pending.
2. Calls `HeadsetSystemInterface.activateVoiceRecognition()`:
   ```java
   Intent intent = new Intent(Intent.ACTION_VOICE_COMMAND);
   intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
   mHeadsetService.startActivity(intent);
   ```
3. Starts a **5 s timeout** (`sStartVrTimeoutMs = 5000`). If the launched app doesn't call `BluetoothHeadset.startVoiceRecognition(device)` in time, it reports failure to the buds.

So:
- **The intent is `android.intent.action.VOICE_COMMAND`** (`Intent.ACTION_VOICE_COMMAND`), started by the Bluetooth system app. Background-start limits don't apply to it.
- It is **not** `ACTION_ASSIST`, and it is **not** `BluetoothHeadset.ACTION_VENDOR_SPECIFIC_HEADSET_EVENT`. That one is only for vendor AT commands such as `+XEVENT`, `+IPHONEACCEV`, `+ANDROID`.
- `AT+BVRA=0` (the buds toggling) → `stopVoiceRecognitionByHeadset`. If a request is still pending it cancels the timeout and replies OK, and **no intent is sent**. So the second hold within 5 s is not visible to apps. **This matches the Windows "later holds may send BVRA=0" behavior: only a BVRA=1 can be detected.**
- While a request is pending (up to 5 s), a new BVRA=1 is rejected. **Realistic limit: about one detectable hold per 5 s.** **[test on device]**: check whether the buds go back to "idle" after the ERROR/timeout so the next hold sends BVRA=1 again.

### Getting Orbit chosen
- Declare an activity with:
  ```xml
  <activity android:name=".HoldTrampolineActivity" android:exported="true"
            android:theme="@android:style/Theme.Translucent.NoTitleBar"
            android:excludeFromRecents="true" android:noHistory="true"
            android:taskAffinity="" android:launchMode="singleInstance"
            android:showWhenLocked="true">
    <intent-filter>
      <action android:name="android.intent.action.VOICE_COMMAND"/>
      <category android:name="android.intent.category.DEFAULT"/>
    </intent-filter>
  </activity>
  ```
- This is ordinary intent resolution. The ASSISTANT role in `roles.xml` has **no preferred activity for VOICE_COMMAND**, so being the default assistant does not route BVRA to you. If more than one app handles it (usually Google app / Gemini), Android shows the chooser the first time and the user taps Orbit → **"Always"**. Privileged system apps can declare a higher intent-filter priority, and if Google's handler does that the chooser may never appear. **[test on device]**: `adb shell cmd package query-activities -a android.intent.action.VOICE_COMMAND` and `adb shell cmd package resolve-activity -a android.intent.action.VOICE_COMMAND`. If the default is already set, the user clears it in App info → "Open by default" → Clear defaults for the current handler.
- **Default digital assistant (ROLE_ASSISTANT)**: `requestable="false"` in roles.xml, so `RoleManager.createRequestRoleIntent(ROLE_ASSISTANT)` doesn't work. The user must pick it in Settings → Default apps → Digital assistant app (`Settings.ACTION_VOICE_INPUT_SETTINGS` / `Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS`). To be eligible you need either an activity for `android.intent.action.ASSIST`, or a full `VoiceInteractionService` (+ `sessionService`, `recognitionService`, `supportsAssist="true"`). That gives you long-press power/home, **not** the BVRA hold. It's optional for Orbit, and it would replace the user's Gemini/Claude assistant, so don't do it by default. https://developer.android.com/reference/android/app/role/RoleManager#ROLE_ASSISTANT
- In the trampoline activity: `onCreate` → tell the service "HOLD", `finish()` right away, `overridePendingTransition(0,0)` (or `overrideActivityTransition` on API 34+). Don't call `BluetoothHeadset.startVoiceRecognition`: that opens an SCO (call-quality) link and pauses A2DP music. Letting the 5 s timeout run is the gentler option.
- Side effect: launching the activity briefly takes focus from the current app, so it pauses/resumes. A translucent, no-animation activity keeps that mostly invisible. A plus: the Orbit process becomes "visible" for a moment, which also covers FGS/background-activity-start exemptions.
- On a locked screen the activity starts behind or over the keyguard (`showWhenLocked`). With the screen off it is still created. **[test on device]**

### Detecting the hold reliably
`VOICE_COMMAND` is the only signal an app can see. HFP AT traffic isn't exposed (no `READ_LOGS`, and `ACTION_VENDOR_SPECIFIC_HEADSET_EVENT` doesn't carry BVRA). Treat "trampoline launched" as `HOLD`, and expect to miss holds that arrive while a request is pending.

```kotlin
class HoldTrampolineActivity : Activity() {
    override fun onCreate(s: Bundle?) {
        super.onCreate(s)
        DialBus.emit(DialEvent.Hold)          // in-process bus to OrbitMediaService / A11y service
        finish()
        overridePendingTransition(0, 0)
    }
}
```

---

## 4. Overlay (radial wheel)

### Which window type
| | `TYPE_APPLICATION_OVERLAY` | `TYPE_ACCESSIBILITY_OVERLAY` |
|---|---|---|
| Needs | `SYSTEM_ALERT_WINDOW` (user grants in "Display over other apps", `Settings.ACTION_MANAGE_OVERLAY_PERMISSION`) | Running `AccessibilityService`, added with *the service's* `WindowManager` |
| Z-order | Below status bar, notification shade, IME | Above most system UI, including the shade |
| Android 12 untrusted-touch rule | A not-touchable overlay from another UID **blocks touches underneath if opacity > 0.8** (`InputManager.getMaximumObscuringOpacityForTouch()`) | Trusted, so pass-through is never blocked |
| Android 15 FGS exemption | SAW only exempts background FGS start while an overlay is **visible** | n/a |

**Recommendation: `TYPE_ACCESSIBILITY_OVERLAY`**. Orbit needs the AccessibilityService anyway for actions, it removes one permission from onboarding, and it avoids the Android 12 touch blocking. Keep SAW as an optional fallback.
- https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_APPLICATION_OVERLAY
- https://developer.android.com/reference/android/view/WindowManager.LayoutParams#TYPE_ACCESSIBILITY_OVERLAY
- https://developer.android.com/about/versions/12/behavior-changes-all#untrusted-touch-events

Flags: `FLAG_NOT_FOCUSABLE or FLAG_NOT_TOUCHABLE or FLAG_LAYOUT_IN_SCREEN or FLAG_LAYOUT_NO_LIMITS` (and `FLAG_HARDWARE_ACCELERATED`), `PixelFormat.TRANSLUCENT`, `WRAP_CONTENT` size centered (a full-screen window with mostly transparent pixels still counts as one window for occlusion). Set `layoutInDisplayCutoutMode = LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS` (API 30) if you go full-screen.

### Compose in a WindowManager window
A `ComposeView` outside an Activity crashes with *"ViewTreeLifecycleOwner not found"* unless you attach owners yourself:
```kotlin
class OverlayOwner : LifecycleOwner, SavedStateRegistryOwner, ViewModelStoreOwner {
    private val lc = LifecycleRegistry(this)
    private val ss = SavedStateRegistryController.create(this)
    override val lifecycle: Lifecycle get() = lc
    override val savedStateRegistry get() = ss.savedStateRegistry
    override val viewModelStore = ViewModelStore()
    fun create() { ss.performRestore(null); lc.currentState = Lifecycle.State.RESUMED }
    fun destroy() { lc.currentState = Lifecycle.State.DESTROYED; viewModelStore.clear() }
}

fun AccessibilityService.showWheel(state: WheelState): View {
    val owner = OverlayOwner().also { it.create() }
    val view = ComposeView(this).apply {
        setViewTreeLifecycleOwner(owner)
        setViewTreeSavedStateRegistryOwner(owner)
        setViewTreeViewModelStoreOwner(owner)
        setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnDetachedFromWindow)
        setContent { RadialWheel(state) }
    }
    val lp = WindowManager.LayoutParams(
        WRAP_CONTENT, WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
        PixelFormat.TRANSLUCENT,
    ).apply { gravity = Gravity.CENTER }
    getSystemService(WindowManager::class.java).addView(view, lp)
    return view   // removeView(view) + owner.destroy() to hide
}
```
Animation: drive the highlight with `animateFloatAsState(target, spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMediumLow))`, or an `Animatable` you `animateTo` on each tick so quick ticks re-target the running spring smoothly. Draw with `Canvas { drawArc(...) }` and `graphicsLayer { rotationZ; scaleX; alpha }`. For open/close use `AnimatedVisibility(scaleIn(spring()) + fadeIn())`, and only `removeView` after the exit animation ends. Keep the view attached and toggle visibility to avoid the first-frame cost of `addView`. Use `View.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)` or `Vibrator` `EFFECT_TICK` on each click. Docs: https://developer.android.com/develop/ui/compose/animation/customize (springs), https://developer.android.com/reference/androidx/lifecycle/ViewTreeLifecycleOwner

---

## 5. Actions without root

### AccessibilityService setup
```xml
<service android:name=".OrbitAccessibilityService" android:exported="false"
         android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE">
  <intent-filter><action android:name="android.accessibilityservice.AccessibilityService"/></intent-filter>
  <meta-data android:name="android.accessibilityservice" android:resource="@xml/orbit_a11y"/>
</service>
```
```xml
<!-- res/xml/orbit_a11y.xml -->
<accessibility-service
    android:accessibilityEventTypes="typeWindowStateChanged"
    android:accessibilityFeedbackType="feedbackGeneric"
    android:accessibilityFlags="flagRequestFilterKeyEvents|flagRetrieveInteractiveWindows"
    android:canPerformGestures="true"
    android:canControlMagnification="true"
    android:canRequestFilterKeyEvents="true"
    android:canRetrieveWindowContent="true"
    android:notificationTimeout="50"
    android:isAccessibilityTool="false"
    android:description="@string/a11y_description"/>
```
Docs: https://developer.android.com/guide/topics/ui/accessibility/service

### Smooth scrolling: `dispatchGesture` with continued strokes (API 26)
`StrokeDescription(path, startTime, duration, willContinue = true)` keeps the virtual finger down. In a *later* `dispatchGesture` (started from `onCompleted`), `prev.continueStroke(nextPath, 0, dur, willContinue)` carries on from the same point. So each dial tick can push the finger another 60–120 px without lifting it, which avoids fling/inertia. Lift (`willContinue=false`) after about 400 ms with no ticks, using a short final segment so it lands as a slow drag, not a fling. Limits: `GestureDescription.getMaxStrokeCount()` (20) and `getMaxGestureDuration()` (60 s). The start point matters: use the centre of the scrollable window (`windows` / `rootInActiveWindow` bounds). Alternative: `AccessibilityNodeInfo.ACTION_SCROLL_FORWARD/BACKWARD` on the focused scrollable node is reliable but moves a whole page per step. API 30+ adds `AccessibilityAction.ACTION_SCROLL_IN_DIRECTION` (API 33) for some views.
https://developer.android.com/reference/android/accessibilityservice/GestureDescription.StrokeDescription

```kotlin
private var stroke: GestureDescription.StrokeDescription? = null
private var fingerY = 0f
fun scrollTick(dy: Float, x: Float, startY: Float) {
    val from = if (stroke == null) startY.also { fingerY = it } else fingerY
    val to = (from - dy).coerceIn(200f, screenH - 200f)
    val p = Path().apply { moveTo(x, from); lineTo(x, to) }
    val s = stroke?.continueStroke(p, 0, 60, true)
        ?: GestureDescription.StrokeDescription(p, 0, 60, true)
    dispatchGesture(GestureDescription.Builder().addStroke(s).build(), object : GestureResultCallback() {
        override fun onCancelled(g: GestureDescription?) { stroke = null }
    }, null)
    stroke = s; fingerY = to
    // when fingerY hits the edge: end the stroke (willContinue=false) and start a new one at startY
}
```
Gestures must not overlap: queue ticks and dispatch the next one from `onCompleted`. If the finger is about to run off the screen, lift and start again from the middle.

### Global actions
`performGlobalAction(id)`: `GLOBAL_ACTION_BACK` (1), `HOME` (2), `RECENTS` (3), `NOTIFICATIONS` (4), `QUICK_SETTINGS` (5), `POWER_DIALOG` (6, API 21), `TOGGLE_SPLIT_SCREEN` (7, API 24), `LOCK_SCREEN` (8, API 28), `TAKE_SCREENSHOT` (9, API 28), `KEYCODE_HEADSETHOOK` (10, API 31), `DISMISS_NOTIFICATION_SHADE` (15, API 31), `DPAD_UP/DOWN/LEFT/RIGHT/CENTER` (16–20, API 33). `MENU` (21) and `MEDIA_PLAY_PAUSE` (22) are newest and `@FlaggedApi` (Android 16+), so feature-check them. https://developer.android.com/reference/android/accessibilityservice/AccessibilityService#performGlobalAction(int)

### App switcher
- **Previous app**: `performGlobalAction(RECENTS)` twice about 150–300 ms apart works with most launchers in 3-button *and* gesture navigation, but timing depends on the launcher. **[test on device]**
- **Real switcher in the wheel**: `UsageStatsManager.queryEvents` (needs `PACKAGE_USAGE_STATS`, granted by the user in `Settings.ACTION_USAGE_ACCESS_SETTINGS`) gives the recent foreground packages. Show icons in the wheel and launch the selection with `packageManager.getLaunchIntentForPackage(pkg)` + `FLAG_ACTIVITY_NEW_TASK`. Background activity launch is allowed because a system-bound AccessibilityService is an exemption: https://developer.android.com/guide/components/activities/background-starts. Alternatively track `TYPE_WINDOW_STATE_CHANGED` package names in the a11y service and skip the usage-stats permission.

### Zoom
`magnificationController.setScale(scale, animate)` / `setCenter(x, y, animate)` / `reset(animate)` (API 24, needs `canControlMagnification`). API 33 adds `MagnificationConfig` + `setMagnificationConfig(config, animate)` with `MAGNIFICATION_MODE_FULLSCREEN` or `MAGNIFICATION_MODE_WINDOW`. Rotation → scale steps of 0.25 between 1.0 and 8.0. https://developer.android.com/reference/android/accessibilityservice/AccessibilityService.MagnificationController

### Brightness
- `Settings.System.SCREEN_BRIGHTNESS` (0–255) needs `WRITE_SETTINGS`, which is a special app-op: `Settings.System.canWrite(ctx)`, and if false send the user to `Settings.ACTION_MANAGE_WRITE_SETTINGS` with `package:` URI. Set `SCREEN_BRIGHTNESS_MODE = SCREEN_BRIGHTNESS_MODE_MANUAL` first, or adaptive brightness will override you. Remember the old mode and restore it when the tool closes.
- Pitfalls: Android 9+ maps the slider on a gamma/perceptual curve, so 0–255 isn't linear with the slider position. Some OEMs (Samsung, Pixel's extra-dim) use different ranges, and the change takes about 100 ms to show. Step in perceptual space (for example square the value) for an even feel.
- Alternative with no permission: `WindowManager.LayoutParams.screenBrightness` on Orbit's own overlay window only applies while the overlay is shown, so it can't be used for a lasting change.
https://developer.android.com/reference/android/provider/Settings.System#SCREEN_BRIGHTNESS, https://developer.android.com/reference/android/provider/Settings#ACTION_MANAGE_WRITE_SETTINGS

### Flashlight
`CameraManager.setTorchMode(cameraId, on)` needs no permission (pick the id where `FLASH_INFO_AVAILABLE` is true). Android 13 (API 33): `turnOnTorchWithStrengthLevel(id, level)` + `getTorchStrengthLevel`, with max from `CameraCharacteristics.FLASH_INFO_STRENGTH_MAXIMUM_LEVEL`. That's a nice fit for rotate-to-dim. Use `registerTorchCallback` to keep the wheel state in sync. It fails if another app has the camera open. https://developer.android.com/reference/android/hardware/camera2/CameraManager#turnOnTorchWithStrengthLevel(java.lang.String,%20int)

### Launching apps / Claude
- Claude Android package: `com.anthropic.claude` (Play listing https://play.google.com/store/apps/details?id=com.anthropic.claude). Launch with `getLaunchIntentForPackage("com.anthropic.claude")`. On API 30+ you need a `<queries><package android:name="com.anthropic.claude"/></queries>` entry to see it. https://developer.android.com/training/package-visibility
- Voice mode: Anthropic's help article only documents starting it by tapping the sound-wave icon in the input field (https://support.claude.com/en/articles/11101966-using-voice-mode). **I found no documented voice-mode deep link or app shortcut, and no confirmation that Claude can hold the ASSISTANT role.** Check on the device:
  - `adb shell dumpsys package com.anthropic.claude | grep -A3 -i "action\|scheme"` (look for VOICE_COMMAND, ASSIST, `claude://` schemes)
  - `adb shell cmd role get-role-holders android.app.role.ASSISTANT`
  - `adb shell cmd shortcut get-shortcuts --user 0 com.anthropic.claude` (static shortcuts; launching them needs launcher privileges, so mostly just informative)
- Fallback when there's no deep link: launch Claude, wait for `TYPE_WINDOW_STATE_CHANGED` from `com.anthropic.claude`, find the voice button node (by content-description or view-id), and `performAction(ACTION_CLICK)`. It breaks when the app UI changes, so keep it behind a setting.
- Nice fit: map **hold** → "Talk to Claude" (open Claude voice mode), since hold already arrives as VOICE_COMMAND.

### Play Store policy for accessibility
From https://support.google.com/googleplay/android-developer/answer/10964491:
- Orbit is **not** an accessibility tool (`isAccessibilityTool="false"`). Launchers, automation and assistants are named as not qualifying.
- Needs an **in-app prominent disclosure** with affirmative consent, separate from the privacy policy, shown before sending the user to Accessibility settings.
- Needs the **Accessibility API declaration form** in Play Console plus a video of the disclosure and the core feature.
- Allowed: deterministic, user-triggered actions ("If Trigger X occurs, perform Action Y"). Not allowed: autonomous planning or acting. Orbit's dial-triggered actions are on the allowed side. Don't read screen content beyond what a feature needs (the Claude-button fallback is the only part that reads nodes, so disclose it).
- `mediaPlayback` FGS for playing silence is a grey area for review ("continuing audio playback"). Describe it honestly, or plan for sideload/F-Droid distribution first.
- Sideloading caveat: on Android 13+, apps installed by a non-store installer that doesn't use install sessions (browser download, some file managers) get **"Restricted settings"**: the Accessibility and Notification-access toggles are greyed out until the user opens App info → ⋮ → "Allow restricted settings". `adb install` and Play installs aren't affected. https://support.google.com/android/answer/12623953

---

## 6. Testing

| Thing to test | Emulator? | How |
|---|---|---|
| Media-button routing (same path as AVRCP) | Yes | `adb shell cmd media_session dispatch play-pause` (also `play`, `pause`, `next`, `previous`). This calls `dispatchMediaKeyEvent` like the BT stack does. Older images: `adb shell media dispatch next`. |
| Key events via the input pipeline | Yes | `adb shell input keyevent KEYCODE_MEDIA_PLAY_PAUSE` (85) / `KEYCODE_MEDIA_NEXT` (87) / `KEYCODE_MEDIA_PREVIOUS` (88) / `KEYCODE_MEDIA_PAUSE` (127). These go to the focused window first, then sessions, so this is slightly different from AVRCP. Also visible to `AccessibilityService.onKeyEvent`. |
| Who owns the buttons | Yes | `adb shell dumpsys media_session` → "Media button session is ...", plus the session stack |
| Rotation (STREAM_MUSIC change from outside) | Yes | `adb shell cmd media_session volume --stream 3 --set 9` (add `--show` to see the panel; `--get` to read). This is a `setStreamVolume`, like the BT stack minus `FLAG_BLUETOOTH_ABS_VOLUME`. Loop it to simulate fast spinning: `for i in 1 2 3; do adb shell cmd media_session volume --stream 3 --set 8; done` |
| Hold | Yes | `adb shell am start -a android.intent.action.VOICE_COMMAND` (tests chooser, "Always" and the trampoline) |
| Real AVRCP absolute volume + merging + panel | **No.** Needs a real phone with the buds | The emulator's virtual Bluetooth (netsim, API 33+ images) can pair emulators but can't act as AVRCP absolute-volume buds. Debug on the device with `adb shell dumpsys bluetooth_manager` (AVRCP "Volume Events" / "Media Key Events" logs from `mVolumeEventLogger`/`mMediaKeyEventLogger`), `adb shell dumpsys audio` (volume event log, `VolChangedBroadcastEvent`), and `adb logcat -s HeadsetService HeadsetStateMachine AvrcpTargetService AvrcpVolumeManager` |
| Accessibility gestures, overlay, global actions | Yes | Enable with `adb shell settings put secure enabled_accessibility_services <pkg>/<svc>` + `adb shell settings put secure accessibility_enabled 1` (dev only) |
| Permissions setup | Yes | `adb shell appops set <pkg> WRITE_SETTINGS allow`, `adb shell appops set <pkg> SYSTEM_ALERT_WINDOW allow`, `adb shell cmd notification allow_listener <pkg>/<listener>`, `adb shell appops set <pkg> GET_USAGE_STATS allow` |
| Android 15 FGS rules | Yes | `adb shell am compat enable FGS_BOOT_COMPLETED_RESTRICTIONS <pkg>`, `adb shell am compat enable FGS_SAW_RESTRICTIONS <pkg>` |

Unit-testable without Android: the gesture decoder (press counts, hold-vs-press, rate-limit merging), the wheel state machine and the delta-from-baseline logic. Write them as pure Kotlin in a `:core` module, mirroring the Python tests in `tests/`.

---

## Recommended design

### Components
1. **`OrbitAccessibilityService`** (centre of the app, started and kept alive by the system once the user enables it, including after reboot):
   - owns the **wheel overlay** (`TYPE_ACCESSIBILITY_OVERLAY` + ComposeView with its own lifecycle owner),
   - runs actions (gestures, global actions, magnification, app launch),
   - filters phone volume keys (`onKeyEvent`) so real key presses aren't counted as dial clicks,
   - starts `OrbitMediaService` when it connects. Use `onServiceConnected`; a bound a11y service can start activities from the background. If the FGS start is ever refused, fall back to a tiny trampoline activity, which gives a visible-app exemption.
2. **`OrbitMediaService`** (foreground, `mediaPlayback`): MediaSession (always PLAYING), looping silent `AudioTrack` with no audio focus, `AudioPlaybackCallback` re-assert, `VOLUME_CHANGED_ACTION` receiver + baseline restore, and the gesture decoder (press counts, holds). It only runs while the buds are the active A2DP/LE output: watch `AudioDeviceCallback` / `BluetoothDevice.ACTION_ACL_CONNECTED`, and stop silence + session when the buds disconnect so the phone's normal media buttons work again.
3. **`OrbitNotificationListener`**: only for `MediaSessionManager.getActiveSessions` → forwarding play/pause/next/prev to the real player when no wheel is open (so single press still controls music).
4. **`HoldTrampolineActivity`**: VOICE_COMMAND handler → `Hold` event (default action: open Claude, or open the wheel).
5. **Main activity**: onboarding, tool picker, settings. Shared in-process `DialBus` (a `SharedFlow`) connects them all; there's one process, so no IPC.

Don't use a `BOOT_COMPLETED` receiver to start the media FGS (Android 15 forbids `mediaPlayback` from boot). The accessibility service connecting at boot is the trigger.

### Permissions / manifest summary
- `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MEDIA_PLAYBACK`, `POST_NOTIFICATIONS` (runtime, 33+)
- `BLUETOOTH_CONNECT` (runtime, 31+). Only needed to read the buds' name/address to know "it's the CMF buds" (`BluetoothDevice.getName`). You can skip it and use `AudioDeviceInfo.productName` instead.
- `BIND_ACCESSIBILITY_SERVICE` service (user toggle), `BIND_NOTIFICATION_LISTENER_SERVICE` service (user toggle)
- `WRITE_SETTINGS` (special app-op, only if the brightness tool is enabled)
- `PACKAGE_USAGE_STATS` (special app-op, only if the recent-apps switcher is enabled)
- `SYSTEM_ALERT_WINDOW`: not needed with the accessibility overlay
- `<queries>` for `com.anthropic.claude` and the launcher intent (`MAIN`/`LAUNCHER`) for the app picker
- No `CAMERA` permission for the torch; no audio-focus request

### Onboarding flow (each step skippable, re-checked on resume)
1. Welcome, then pick the buds from connected audio devices (asks `BLUETOOTH_CONNECT` only if needed).
2. Notifications permission (FGS/media card).
3. **Accessibility**: prominent-disclosure screen (what is read/done, consent button) → `Settings.ACTION_ACCESSIBILITY_SETTINGS`. If the toggle is greyed out, show the "Allow restricted settings" guide.
4. **Notification access** (for forwarding to your music player) → `Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS`.
5. **Hold setup**: fire `ACTION_VOICE_COMMAND` yourself and tell the user to choose Orbit → "Always". Detect success with `packageManager.resolveActivity(Intent(ACTION_VOICE_COMMAND), MATCH_DEFAULT_ONLY)?.activityInfo?.packageName == packageName`. If Google already holds the default, deep-link to its App info to clear defaults.
6. Optional per tool: Modify system settings (brightness), Usage access (app switcher), battery-optimization exemption (`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` needs Play justification, so link to the settings page instead).
7. **Calibrate**: "turn the dial 5 clicks right, then 5 left", record step size and lost clicks, choose the baseline, and warn the user that the system volume panel will flash.

### Biggest risks
1. **The volume panel flashes on every click.** The BT stack calls `setStreamVolume(... FLAG_SHOW_UI ...)` and the only non-root workaround is the untested "disable absolute volume" idea.
2. **Losing media-button ownership** to real players. The silence + re-assert approach depends on OEM `MediaSessionService` behavior, costs battery, and makes Orbit look like the "now playing" app.
3. **Hold is limited.** About one BVRA=1 per 5 s, BVRA=0 toggles are invisible, and Google's VOICE_COMMAND handler may win resolution on some devices.
4. **Lost or merged clicks.** Step rounding (AVRCP 0–127 vs 15 steps) plus broadcast merging, so it needs per-device calibration.
5. **Policy and onboarding friction.** An accessibility service that isn't an accessibility tool, plus a `mediaPlayback` FGS playing silence. Sideloaded builds hit "restricted settings". Plan to distribute outside Play first.
6. **OEM differences** (Samsung/Xiaomi often patch both the Bluetooth stack and the volume UI). All the [test on device] items above should be checked on the target phone first.
