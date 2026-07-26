# mopidy 本体プロセス(=実際に CoreAudio へ音を出している本人)から macOS の Now Playing に
# 名乗り出るフロントエンド。別ヘルパでは macOS 26 に弾かれるが、音源本人が登録すれば
# 再生中アプリとして認識され、コントロールセンター表示・AirPods/メディアキーの操作
# (MPRemoteCommandCenter 経由) が本人へ届く。pyobjc で MediaPlayer.framework を動的ロード。
import logging

import pykka
from mopidy import core

logger = logging.getLogger(__name__)

try:
    import objc
    from Foundation import NSBundle

    NSBundle.bundleWithPath_(
        "/System/Library/Frameworks/MediaPlayer.framework"
    ).load()
    _MP = objc.lookUpClass("MPNowPlayingInfoCenter")
    _RC = objc.lookUpClass("MPRemoteCommandCenter")
    # pyobjc-framework-MediaPlayer が無いと addTargetWithHandler: のブロック署名メタが
    # 欠けて "no signature available" になる。手動でブロック署名を登録する。
    # ブロック: MPRemoteCommandHandlerStatus(=NSInteger 'q') (^)(MPRemoteCommandEvent* '@')
    objc.registerMetaDataForSelector(
        b"MPRemoteCommand",
        b"addTargetWithHandler:",
        {
            "arguments": {
                2: {
                    "type": b"@?",
                    "callable": {
                        "retval": {"type": b"q"},
                        "arguments": {
                            0: {"type": b"^v"},
                            1: {"type": b"@"},
                        },
                    },
                }
            }
        },
    )
    _AVAILABLE = True
except Exception:  # pragma: no cover
    logger.exception("nowplaying: MediaPlayer framework unavailable")
    _AVAILABLE = False

# MPMediaItemProperty* / MPNowPlayingInfoProperty* の生の文字列値 (安定)
K_TITLE = "title"
K_ARTIST = "artist"
K_ALBUM = "albumTitle"
K_DURATION = "playbackDuration"
K_ELAPSED = "MPNowPlayingInfoPropertyElapsedPlaybackTime"
K_RATE = "MPNowPlayingInfoPropertyPlaybackRate"

# MPNowPlayingPlaybackState
PS_PLAYING = 1
PS_PAUSED = 2
PS_STOPPED = 3


class NowPlayingFrontend(pykka.ThreadingActor, core.CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.core = core
        self.center = _MP.defaultCenter() if _AVAILABLE else None
        self._handlers = []  # ブロックの参照を保持(GC 防止)

    def on_start(self):
        if not _AVAILABLE:
            return
        try:
            self._setup_commands()
        except Exception:
            logger.exception("nowplaying: remote command setup failed")
        self._update()

    def _setup_commands(self):
        cc = _RC.sharedCommandCenter()

        def register(command, fn):
            def handler(event):
                try:
                    fn()
                except Exception:
                    logger.exception("nowplaying: command failed")
                return 0  # MPRemoteCommandHandlerStatusSuccess

            self._handlers.append(handler)
            command.setEnabled_(True)
            command.addTargetWithHandler_(handler)

        register(cc.playCommand(), self._play)
        register(cc.pauseCommand(), lambda: self.core.playback.pause())
        register(cc.togglePlayPauseCommand(), self._toggle)
        register(cc.nextTrackCommand(), lambda: self.core.playback.next())
        register(cc.previousTrackCommand(), lambda: self.core.playback.previous())
        register(cc.stopCommand(), lambda: self.core.playback.pause())

    def _play(self):
        # 一時停止中は resume で復帰、それ以外は play で開始 (play() は再開しない)
        if self.core.playback.get_state().get() == "paused":
            self.core.playback.resume()
        else:
            self.core.playback.play()

    def _toggle(self):
        if self.core.playback.get_state().get() == "playing":
            self.core.playback.pause()
        else:
            self._play()

    def _update(self):
        if not _AVAILABLE:
            return
        try:
            tl = self.core.playback.get_current_tl_track().get()
            state = self.core.playback.get_state().get()
            if tl is None or state == "stopped":
                self.center.setNowPlayingInfo_(None)
                self.center.setPlaybackState_(PS_STOPPED)
                return
            t = tl.track
            pos = (self.core.playback.get_time_position().get() or 0) / 1000.0
            info = {
                K_TITLE: t.name or "",
                K_ARTIST: ", ".join(a.name for a in (t.artists or []) if a.name),
                K_ALBUM: (t.album.name if t.album else "") or "",
                K_DURATION: float((t.length or 0) / 1000.0),
                K_ELAPSED: float(pos),
                K_RATE: 1.0 if state == "playing" else 0.0,
            }
            self.center.setNowPlayingInfo_(info)
            self.center.setPlaybackState_(PS_PLAYING if state == "playing" else PS_PAUSED)
        except Exception:
            logger.exception("nowplaying: update failed")

    # CoreListener イベント
    def track_playback_started(self, tl_track):
        self._update()

    def track_playback_paused(self, tl_track, time_position):
        self._update()

    def track_playback_resumed(self, tl_track, time_position):
        self._update()

    def track_playback_ended(self, tl_track, time_position):
        self._update()

    def playback_state_changed(self, old_state, new_state):
        self._update()

    def seeked(self, time_position):
        self._update()
