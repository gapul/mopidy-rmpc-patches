# mopidy_mpd/protocol/playback.py の `next`/`previous` が、再生中でない(完全停止中)
# 状態でも一切確認せず無条件で `context.core.playback.next()`/`previous()` を呼んで
# しまい、実MPDならACKで拒否すべき操作をサイレントに実行しキューの現在位置
# ポインタまで実際に動かしてしまう不具合。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# 実MPD本体(gh rawで`src/queue/PlaylistControl.cxx`の`playlist::PlayNext()`/
# `playlist::PlayPrevious()`を確認)はどちらも先頭で
#   if (!playing) throw PlaylistError::NotPlaying();
# を無条件で行う。`playing`はSTOPPEDでは常にfalseで、`PlaylistResult::NOT_PLAYING`は
# `src/command/CommandError.cxx`の`ToAck()`で`ACK_ERROR_PLAYER_SYNC`(55、メッセージ
# "Not playing"固定)に写像される。これは`seekcur`(mpdseekcurstop-patch.py)が
# `playlist::SeekCurrent()`の同じ`!playing`ガードに対して既に実装済みのパターンと
# 全く同一の非対称性が`next`/`previous`にも残っていたもの
# (mpdoneshotmanualskip-patch.py/mpdoneshotmanualskipguard-patch.py/
# mpdpreviousrepeat-patch.pyはnext/previousのoneshot revert挙動や曲送りアルゴリズム
# 自体は精査済みだが、そもそも停止中に呼べてしまうこと自体は未対応のまま残っていた)。
#
# 実害: `stop`後(一度でも再生した曲があれば`get_current_tl_track()`は非Noneのまま
# 残り続ける、mpdseekcurstop-patch.py参照)に`next`を送ると実MPDなら
# `ACK [55@0] {next} Not playing`になるところ、mopidy-mpdは`OK`を返した上で
# `status`の`song`/`songid`が実際に次の曲へ進んでしまう(stateはstopのまま)。
# rmpc-mpd(rmpc-mpd/src/mpd_client.rs)はキュー操作後の同期や次曲プリフェッチ等で
# `next`/`previous`を送りうるため、停止中にクライアントの意図しないキュー位置変化が
# サイレントに起こりうる。
#
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント): `clear`+`findadd`で2曲キュー投入
# ->`play "0"`->`status`で`state: play`/`song: 0`/`songid: 1`確認->`stop`->
# `status`で`state: stop`/`song: 0`/`songid: 1`(現在曲保持、実MPD仕様通り)->`next`
# が修正前`OK`を返し直後の`status`が`state: stop`のまま`song: 1`/`songid: 2`へ
# サイレントに進行してしまうことを確認。
#
# 修正: `seekcur`(mpdseekcurstop-patch.py)が既に定義済みの
# `_MpdSeekCurPlayerSyncError`(`error_code = ACK_ERROR_PLAYER_SYNC`)を同一モジュール
# 内でそのまま再利用し(Pythonのモジュールレベル関数は呼び出し時点で解決されるため
# 定義順は無関係、mpdoneshotmanualskip-patch.py等のswap()前方参照と同じ要領)、
# next_()/previous()の先頭で`get_state() == PlaybackState.STOPPED`なら既存の
# oneshot記録/曲送りロジックへ到達させず即座に`ACK Not playing`を返す。
# `stop`自体(mpdoneshotstop-patch.py)や、STOPPED以外(PLAY/PAUSE)での既存の
# oneshot revert挙動・previous()のrepeat/consumeアルゴリズム(mpdpreviousrepeat-patch.py)
# は無変更。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

NEXT_OLD = (
    '    if context.core.playback.get_current_tl_track().get() is not None:\n'
    '        translator.mark_pending_manual_track_change("next")\n'
    "    return context.core.playback.next().get()\n"
)
NEXT_NEW = (
    "    if context.core.playback.get_state().get() == PlaybackState.STOPPED:\n"
    '        # 実MPDのPlayNext()も!playing(PLAY/PAUSE状態でない)を無条件でNotPlaying扱いする。\n'
    '        raise _MpdSeekCurPlayerSyncError("Not playing")\n'
    '    if context.core.playback.get_current_tl_track().get() is not None:\n'
    '        translator.mark_pending_manual_track_change("next")\n'
    "    return context.core.playback.next().get()\n"
)

PREV_OLD = (
    "    current_tl_track = context.core.playback.get_current_tl_track().get()\n"
    "    if current_tl_track is not None:\n"
    '        translator.mark_pending_manual_track_change("previous")\n'
    "    if current_tl_track is not None and not context.core.tracklist.get_random().get():\n"
)
PREV_NEW = (
    "    if context.core.playback.get_state().get() == PlaybackState.STOPPED:\n"
    '        # 実MPDのPlayPrevious()も!playing(PLAY/PAUSE状態でない)を無条件でNotPlaying扱いする。\n'
    '        raise _MpdSeekCurPlayerSyncError("Not playing")\n'
    "    current_tl_track = context.core.playback.get_current_tl_track().get()\n"
    "    if current_tl_track is not None:\n"
    '        translator.mark_pending_manual_track_change("previous")\n'
    "    if current_tl_track is not None and not context.core.tracklist.get_random().get():\n"
)

if NEXT_NEW in s and PREV_NEW in s:
    print("next()/previous() stopped-guard already patched, skip")
else:
    assert s.count(NEXT_OLD) == 1, f"NEXT_OLD count={s.count(NEXT_OLD)}"
    assert s.count(PREV_OLD) == 1, f"PREV_OLD count={s.count(PREV_OLD)}"
    s = s.replace(NEXT_OLD, NEXT_NEW, 1)
    s = s.replace(PREV_OLD, PREV_NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: next/previousが完全停止中(state==STOPPED)でも"
        "無条件でcore.playback.next()/previous()を呼びキュー位置をサイレントに"
        "進めてしまう不具合を修正 (ACK Not playingへ、seekcurと同じ_MpdSeekCurPlayerSyncErrorを再利用)"
    )
