# `next`が一時停止中(state==PAUSE)に送られても再生状態をそのまま保持してしまい、
# 曲だけ切り替わって無音のまま止まったように見える不具合。TODO全項目消化済みのため
# 自走エージェントが(general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# mopidy core本体(mopidy/core/playback.py PlaybackController.next())は自身の
# docstringに明記している通り"The current playback state will be kept. If it
# was playing, playing will continue. If it was paused, it will still be
# paused, etc."という設計で、pending_tl_trackがある限り現在のstateをそのまま
# backend.playback.pause()/play()へ渡す(_change())。
#
# 実MPD本体(gh rawでsrc/queue/PlaylistControl.cxx playlist::PlayNext()を確認)は
# 次の曲がある限り必ずPlayOrder()->pc.Play()を呼び、src/player/Control.cxx
# PlayerControl::Play()は
#   if (state == PlayerState::PAUSE) PauseLocked(lock); // unpause
# と、一時停止中だった場合は無条件で解除して再生を再開する。つまり実MPDの
# next/previousはどちらも「常に再生を再開する」動作であり、mopidy coreの
# 「状態を保持する」という設計そのものが実MPD仕様と逆。
#
# この非対称は既にnext/previousの片方だけ修正済みだった: mpdpreviousrepeat-patch.py
# がrepeat/consume時の折り返し不具合を直すためprevious()のrandom無効分岐を
# context.core.playback.play(tl_tracks[new_position])(常にPLAYINGを強制する
# 実装)へ書き換えており、副産物としてprevious側だけpause保持バグが直っていた。
# next()側は素のcontext.core.playback.next().get()のままのため非対称が残る。
#
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント、YOASOBIで2曲キュー投入):
# `play "0"`->`pause 1`->`status`で`state: pause`/`song: 0`確認->`next`->
# 数秒後`status`が修正前`song: 1`(曲は切り替わっている)なのに`state: pause`の
# まま(実際に音も鳴らない)ことを確認。同一状態から`previous`を送ると
# `state: play`へ正しく戻ることも確認し、next/previousの非対称を直接確認した。
#
# rmpc側の到達性: rmpc/src/shared/mpd_client_ext.rs の next_keep_state()は
# `keep_state_on_song_change`設定(デフォルトtrue)がtrueの間はpauseだった場合
# next送信後に明示的にpauseを追加送信して補っているため今回の不具合はデフォルト
# 設定では表面化しないが、ユーザがこの設定をfalse(「曲送りで状態を保持しない
# =実MPD標準動作」を意図)にすると、既定キーバインドのNextTrackが素のnextだけを
# 送るため一時停止中に曲送りしても無音のまま再生が始まらない不具合になる。
#
# 修正: next_()が呼ばれる直前の状態がPAUSEDだった場合のみ、next()実行後になお
# PAUSEDのまま(=次の曲が実在し、backend側がpause状態を維持した)であれば
# context.core.playback.resume()で明示的に再開する。next()がキュー末尾で
# self.stop()経由のSTOPPEDへ遷移した場合(実MPDのPlayNext()もこのケースのみ
# PlayOrder()を経由せずStop()を呼ぶ)はガード条件(なおPAUSEDのまま)を満たさず
# resume()は呼ばれない。previous()の折り返し・oneshot記録・停止中ガード
# (mpdnextprevstopguard-patch.py)は無変更。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

NEW = (
    "    if context.core.playback.get_state().get() == PlaybackState.STOPPED:\n"
    "        # 実MPDのPlayNext()も!playing(PLAY/PAUSE状態でない)を無条件でNotPlaying扱いする。\n"
    '        raise _MpdSeekCurPlayerSyncError("Not playing")\n'
    "    was_paused = context.core.playback.get_state().get() == PlaybackState.PAUSED\n"
    "    if context.core.playback.get_current_tl_track().get() is not None:\n"
    '        translator.mark_pending_manual_track_change("next")\n'
    "    result = context.core.playback.next().get()\n"
    "    if was_paused and context.core.playback.get_state().get() == PlaybackState.PAUSED:\n"
    "        # 実MPDのPlayOrder()->Play()は一時停止中だった場合、次の曲へ切り替えた上で\n"
    "        # 無条件に一時停止を解除する。mopidy coreのnext()は逆に状態を保持するため\n"
    "        # ここで明示的に再開する(キュー末尾でSTOPPEDへ落ちた場合はこの分岐に来ない)。\n"
    "        context.core.playback.resume().get()\n"
    "    return result\n"
)

if NEW in s:
    print("next() pause-resume fix already patched, skip")
else:
    OLD = (
        "    if context.core.playback.get_state().get() == PlaybackState.STOPPED:\n"
        "        # 実MPDのPlayNext()も!playing(PLAY/PAUSE状態でない)を無条件でNotPlaying扱いする。\n"
        '        raise _MpdSeekCurPlayerSyncError("Not playing")\n'
        "    if context.core.playback.get_current_tl_track().get() is not None:\n"
        '        translator.mark_pending_manual_track_change("next")\n'
        "    return context.core.playback.next().get()\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: next()が一時停止中でも状態を保持し続け"
        "曲だけ切り替わって無音のまま止まる不具合を修正 (実MPD同様next後に自動再開)"
    )
