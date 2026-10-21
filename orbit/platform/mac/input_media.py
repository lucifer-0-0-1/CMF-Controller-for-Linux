"""macOS: dial presses via MPRemoteCommandCenter.

The buds' AVRCP play/pause/next/previous go to the "now playing" app. Orbit
becomes it: registers the commands, sets playbackState = Playing (macOS does not
infer it - developer.apple.com/forums/thread/685333) and loops silence through
AVAudioEngine so it stays the most recent player.

    toggle / play / pause -> CLICK,  next -> DOUBLE,  previous -> TRIPLE

When a press starts a real player (Orbit forwards play/pause to Spotify / Music),
that player becomes now-playing and the buds' presses go to it, not us (Mac test,
Oct 2026). So after every forwarded press, and whenever the dial turns, Orbit takes
now-playing back with a real state change (paused -> playing, fresh now-playing
info, silent audio restarted); re-announcing "playing" alone changes nothing.

Handlers run on the main thread; Qt's event loop on macOS is the Cocoa run loop,
so blocks dispatched there are serviced.
"""
from __future__ import annotations

import logging
import time

from orbit.core.events import Capability, InputEvent, Kind
from orbit.platform.base import Emit, InputSource

log = logging.getLogger("orbit.media")
SESSION_TITLE = "Orbit Dial"


class MacMediaButtonSource(InputSource):
    name = "mpremote"
    capabilities = frozenset({Capability.CLICKS})

    def __init__(self):
        self._emit: Emit | None = None
        self._engine = None          # the looping silent AVAudioPlayer
        self._handlers = []          # keep blocks alive
        self._last_assert = 0.0

    def start(self, emit):
        from MediaPlayer import (MPMediaItemPropertyArtist, MPMediaItemPropertyTitle,
                                 MPNowPlayingInfoCenter, MPRemoteCommandCenter)

        self._emit = emit
        cc = MPRemoteCommandCenter.sharedCommandCenter()
        for cmd, kind in ((cc.togglePlayPauseCommand(), Kind.CLICK), (cc.playCommand(), Kind.CLICK),
                          (cc.pauseCommand(), Kind.CLICK), (cc.nextTrackCommand(), Kind.DOUBLE),
                          (cc.previousTrackCommand(), Kind.TRIPLE)):
            h = self._handler(kind)
            self._handlers.append(h)
            cmd.setEnabled_(True)
            cmd.addTargetWithHandler_(h)
        MPNowPlayingInfoCenter.defaultCenter().setNowPlayingInfo_(
            {MPMediaItemPropertyTitle: SESSION_TITLE, MPMediaItemPropertyArtist: "dial input"})
        self._start_silence()
        self.reassert()
        log.info("now-playing session active")

    def _handler(self, kind):
        def h(event):
            if self._emit:
                self._emit(InputEvent(kind, 0, self.name))
            return 0          # MPRemoteCommandHandlerStatusSuccess
        return h

    def _start_silence(self):
        """Loop a silent WAV with AVAudioPlayer. (AVAudioEngine's mixer graph crashed natively
        when the output device was unusual - seen on a CI Mac - so keep this minimal.)"""
        import tempfile
        import wave
        from pathlib import Path

        from AVFoundation import AVAudioPlayer
        from Foundation import NSURL

        path = Path(tempfile.gettempdir()) / "orbit-silence.wav"
        if not path.exists():
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
                w.writeframes(b"\x00\x00" * 22050)
        player, err = AVAudioPlayer.alloc().initWithContentsOfURL_error_(NSURL.fileURLWithPath_(str(path)), None)
        if player is None:
            log.warning("silent player failed: %s (presses may go to other apps)", err)
            return
        player.setNumberOfLoops_(-1)
        if not player.play():
            log.warning("silent player did not start (no audio output?)")
        self._engine = player

    def reassert(self):
        """Become the now-playing app again (another player may have taken over). It
        takes a state *change*: setting Playing while already Playing is ignored."""
        from MediaPlayer import (MPMediaItemPropertyArtist, MPMediaItemPropertyTitle,
                                 MPNowPlayingInfoCenter, MPNowPlayingInfoPropertyElapsedPlaybackTime,
                                 MPNowPlayingInfoPropertyPlaybackRate, MPNowPlayingPlaybackStatePaused,
                                 MPNowPlayingPlaybackStatePlaying)

        center = MPNowPlayingInfoCenter.defaultCenter()
        center.setPlaybackState_(MPNowPlayingPlaybackStatePaused)
        center.setNowPlayingInfo_({MPMediaItemPropertyTitle: SESSION_TITLE, MPMediaItemPropertyArtist: "dial input",
                                   MPNowPlayingInfoPropertyElapsedPlaybackTime: 0.0,
                                   MPNowPlayingInfoPropertyPlaybackRate: 1.0})
        if self._engine is not None:
            self._engine.stop()
            self._engine.setCurrentTime_(0)
            self._engine.play()                       # a fresh start makes us the latest player
        center.setPlaybackState_(MPNowPlayingPlaybackStatePlaying)
        self._last_assert = time.monotonic()

    def observe(self, ev):
        from PyObjCTools import AppHelper
        if ev.source == self.name and ev.kind in (Kind.CLICK, Kind.TRIPLE):
            # we just forwarded play/pause (or previous) to the real player, which then
            # claims now-playing: take it back once it has settled
            AppHelper.callAfter(lambda: AppHelper.callLater(0.9, self._safe_reassert))
            return
        # the wheel is about to need presses: make sure they'll come to us
        if ev.kind in (Kind.ROTATE, Kind.DOUBLE) and time.monotonic() - self._last_assert > 2.0:
            self._last_assert = time.monotonic()
            AppHelper.callAfter(self._safe_reassert)     # observe() runs on source threads

    def _safe_reassert(self):
        try:
            self.reassert()
        except Exception:
            log.exception("reassert failed")

    def stop(self):
        try:
            from MediaPlayer import MPNowPlayingInfoCenter
            MPNowPlayingInfoCenter.defaultCenter().setPlaybackState_(3)   # stopped
            if self._engine is not None:
                self._engine.stop()
        except Exception:
            pass
