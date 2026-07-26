# `stop` コマンドが `single "oneshot"`/`consume "oneshot"` を意図せず off へ
# 戻してしまう不具合。TODO 全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# mopidy_mpd の `stop()` (playback.py) は `context.core.playback.stop()` を
# 呼ぶだけで、next/previous (mpdoneshotmanualskip-patch.py) と違い
# `translator.mark_pending_manual_track_change()` を呼ばない。一方 mopidy core
# 本体 (`mopidy/core/playback.py`) の `stop()` は状態が STOPPED でなければ
# backend を止めた後 `set_state(STOPPED)` するのみだが、GStreamer が NULL へ
# 遷移すると `_on_stream_changed(None)` が呼ばれ ("This code path handles the
# stop() case, uri should be none." とコード自身のコメントに明記) そこで
# `_trigger_track_playback_ended()` が発火する。つまり明示 `stop` も
# next/previous と同じ `track_playback_ended` イベント経路を通ってしまい、
# actor.py の `_revert_oneshot()` がコマンド由来を区別できず single/consume
# 両方を無条件に off へ戻していた。
#
# 実MPD本体 (gh rawで直接確認):
# - `src/queue/PlaylistControl.cxx` `playlist::Stop()`: `pc.LockStop()` /
#   `queued = -1` / `playing = false` / (random時のみ) シャッフルのみを行い、
#   `queue.single`/`queue.consume` には一切触れない。
# - `src/queue/Playlist.cxx` `playlist::BorderPause()` (single を ONE_SHOT から
#   off へ戻す唯一の箇所): 対象曲の自然な再生終了経由でのみ呼ばれ、`Stop()`
#   からは呼ばれない。
# - `src/queue/Playlist.cxx` `playlist::QueuedSongStarted()` (consume を
#   ONE_SHOT から off へ戻す唯一の箇所): 次曲へ実際に遷移した時点でのみ呼ばれ、
#   `Stop()` からは呼ばれない。
# つまり実MPDでは明示 `stop` は single/consume の oneshot 状態を一切変更しない。
#
# 実機確認 (TCP 6601, mopidy-ytmusic実アカウント): `searchadd`で実トラックを
# 積み`single "oneshot"`後`play "0"`→`stop`を送ると`status`の`single`が
# `oneshot`から`0`へ誤って戻ることを確認。`consume "oneshot"`でも同様。
#
# 修正: `stop()`がcoreへ委譲する直前に(実際に状態変化を起こす場合のみ、
# mpdoneshotmanualskipguard-patch.pyのnext/previousと同じ no-op 除外の
# 考え方で) `translator.mark_pending_manual_track_change("stop")` を記録し、
# `_revert_oneshot()` (actor.py) は `stop` 由来を `previous` と同じく
# 「single/consume どちらも戻さない」扱いにする。

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = 'mark_pending_manual_track_change("stop")'
if MARKER in s:
    print("playback.py already patched, skip")
else:
    old_stop = (
        '@protocol.commands.add("stop")\n'
        "def stop(context):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``stop``\n"
        "\n"
        "        Stops playing.\n"
        '    """\n'
        "    context.core.playback.stop().get()\n"
    )
    assert s.count(old_stop) == 1, f"old_stop count={s.count(old_stop)}"
    new_stop = (
        '@protocol.commands.add("stop")\n'
        "def stop(context):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``stop``\n"
        "\n"
        "        Stops playing.\n"
        '    """\n'
        "    if context.core.playback.get_state().get() != PlaybackState.STOPPED:\n"
        '        translator.mark_pending_manual_track_change("stop")\n'
        "    context.core.playback.stop().get()\n"
    )
    s = s.replace(old_stop, new_stop, 1)
    open(pp, "w").write(s)
    print(
        "patched playback.py: stop送信直前に明示コマンド種別(stop)を記録"
    )

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER2 = 'command in ("previous", "stop")'
if MARKER2 in a:
    print("actor.py already patched, skip")
else:
    old_revert = (
        "        command = translator.pop_pending_manual_track_change()\n"
        '        if command == "previous":\n'
        "            return\n"
    )
    assert a.count(old_revert) == 1, f"old_revert count={a.count(old_revert)}"
    new_revert = (
        "        command = translator.pop_pending_manual_track_change()\n"
        '        if command in ("previous", "stop"):\n'
        "            return\n"
    )
    a = a.replace(old_revert, new_revert, 1)
    open(ap, "w").write(a)
    print(
        "patched actor.py: _revert_oneshot()がstop由来の場合もsingle/consumeを"
        "戻さないよう修正(実MPDのStop()と同様)"
    )
