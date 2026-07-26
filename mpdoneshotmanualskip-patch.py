# `single "oneshot"` (mpdoneshot-patch.py で対応済み) が、対象曲の自然な再生終了を
# 待たず、`next`/`previous` (rmpc の通常のスキップ操作) を送っただけで即座に off へ
# 戻ってしまう不具合。TODO 全項目消化済みのため自走エージェントが調査で発見した。
#
# 実MPD (MusicPlayerDaemon/MPD, gh rawで直接確認) の該当ソース:
# - `src/queue/PlaylistControl.cxx` `playlist::PlayNext()` (明示 `next` コマンド):
#   `queue.consume == ConsumeMode::ONE_SHOT` なら off に戻す処理はあるが、
#   `queue.single` には一切触れない。
# - `src/queue/PlaylistControl.cxx` `playlist::PlayPrevious()` (明示 `previous`
#   コマンド): single/consume のどちらにも一切触れない。
# - `src/queue/Playlist.cxx` `playlist::BorderPause()`: `queue.single ==
#   SingleMode::ONE_SHOT` を off に戻すのはここだけで、`src/player/Thread.cxx`
#   `Player::SongBorder()` (対象曲の再生が自然に (次曲へのギャップレス遷移として)
#   終端に達した時にのみ player thread から呼ばれる) 経由でしか呼ばれない。
#   `PlayNext()`/`PlayPrevious()` からは呼ばれない。
# - `src/queue/Playlist.cxx` `playlist::QueuedSongStarted()` (自然遷移で
#   キュー済み曲の再生が実際に始まった時点、player thread からの通知契機):
#   consume が ONE_SHOT ならここでも off に戻す (`next` と同じく consume 側は
#   自然終了でも off に戻る)。
#
# まとめると実MPDは: single の oneshot は「自然な曲送り」でのみ off に戻り、
# `next`/`previous` 等の明示コマンドでは一切変更されない。consume の oneshot は
# 「自然な曲送り」と明示 `next` の両方で off に戻るが、明示 `previous` では
# 変更されない。
#
# mopidy core の `track_playback_ended` イベント (mopidy/core/playback.py
# `_on_stream_changed`/`_on_end_of_stream`) は上記のどの経路 (自然遷移/明示
# next/明示 previous) でも区別なく発火するため、mopidy_mpd 側の
# `MpdFrontend._revert_oneshot()` (mpdoneshot-patch.py) がこのイベント1本だけを
# 見て single/consume 両方を無条件に off へ戻しており、`next`/`previous` を
# 送っただけで single "oneshot" が (対象曲の再生継続中にも関わらず) 消えてしまう。
#
# 実装: `next`/`previous` コマンドハンドラ (playback.py) が
# `context.core.playback.next()/previous()` を呼ぶ直前に、次に届く
# `track_playback_ended` がどちらの明示コマンドに由来するかを揮発性ストア
# (translator.py) へ記録する。`_revert_oneshot()` (actor.py) はそれを読み取り、
# `previous` 由来なら single/consume どちらも戻さず、`next` 由来なら consume の
# みを戻し、記録がない (自然遷移) 場合のみ従来通り両方戻す。

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = "mark_pending_manual_track_change"
if MARKER in s:
    print("playback.py already patched, skip")
else:
    old_next_tail = (
        "          order as the first time.\n"
        "\n"
        '    """\n'
        "    return context.core.playback.next().get()\n"
    )
    assert s.count(old_next_tail) == 1, f"old_next_tail count={s.count(old_next_tail)}"
    new_next_tail = (
        "          order as the first time.\n"
        "\n"
        '    """\n'
        '    translator.mark_pending_manual_track_change("next")\n'
        "    return context.core.playback.next().get()\n"
    )
    s = s.replace(old_next_tail, new_next_tail, 1)

    old_previous_tail = (
        "        - If :attr:`time_position` of the current track is 15s or more,\n"
        "          ``previous`` should do a seek to time position 0.\n"
        "\n"
        '    """\n'
        "    return context.core.playback.previous().get()\n"
    )
    assert s.count(old_previous_tail) == 1, (
        f"old_previous_tail count={s.count(old_previous_tail)}"
    )
    new_previous_tail = (
        "        - If :attr:`time_position` of the current track is 15s or more,\n"
        "          ``previous`` should do a seek to time position 0.\n"
        "\n"
        '    """\n'
        '    translator.mark_pending_manual_track_change("previous")\n'
        "    return context.core.playback.previous().get()\n"
    )
    s = s.replace(old_previous_tail, new_previous_tail, 1)

    open(pp, "w").write(s)
    print(
        "patched playback.py: next/previous 送信直前に明示コマンド種別を記録"
    )

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER2 = "_pending_manual_track_change"
if MARKER2 in t:
    print("translator.py already patched, skip")
else:
    anchor = (
        "def get_consume_state():\n"
        "    return _consume_state\n"
    )
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    addition = (
        "\n"
        "\n"
        "# next/previous (playback.py) が実際に mopidy core へコマンドを渡す直前に\n"
        "# 記録する、直後に届く track_playback_ended の由来。actor.py の\n"
        "# _revert_oneshot() が single/consume oneshot を戻す判断に使う\n"
        "# (mpdoneshotmanualskip-patch.py)。\n"
        '_pending_manual_track_change = None\n'
        "\n"
        "\n"
        "def mark_pending_manual_track_change(command):\n"
        "    global _pending_manual_track_change\n"
        "    _pending_manual_track_change = command\n"
        "\n"
        "\n"
        "def pop_pending_manual_track_change():\n"
        "    global _pending_manual_track_change\n"
        "    command = _pending_manual_track_change\n"
        "    _pending_manual_track_change = None\n"
        "    return command\n"
    )
    t = t.replace(anchor, anchor + addition, 1)
    open(tp, "w").write(t)
    print(
        "patched translator.py: next/previous 由来を記録する揮発性ストアを追加"
    )

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER3 = "pop_pending_manual_track_change"
if MARKER3 in a:
    print("actor.py already patched, skip")
else:
    old_revert = (
        "    def _revert_oneshot(self):\n"
        "        # 実 MPD 同様、single/consume の oneshot は対象の1曲の再生が終わったら\n"
        "        # off に自動で戻る (musicpd.org protocol, single/consume oneshot mode)。\n"
        '        if translator.get_single_state() == "oneshot":\n'
        '            translator.set_single_state("0")\n'
        "            self.core.tracklist.set_single(False).get()\n"
        '        if translator.get_consume_state() == "oneshot":\n'
        '            translator.set_consume_state("0")\n'
        "            self.core.tracklist.set_consume(False).get()\n"
    )
    assert a.count(old_revert) == 1, f"old_revert count={a.count(old_revert)}"
    new_revert = (
        "    def _revert_oneshot(self):\n"
        "        # 実 MPD (PlaylistControl.cxx PlayNext()/PlayPrevious(), Playlist.cxx\n"
        "        # BorderPause()/QueuedSongStarted()) の挙動: single の oneshot は\n"
        "        # 自然な曲送りでのみ off に戻り、next/previous 等の明示コマンドでは\n"
        "        # 変更されない。consume の oneshot は自然な曲送りと明示 next の両方で\n"
        "        # off に戻るが、明示 previous では変更されない\n"
        "        # (mpdoneshotmanualskip-patch.py)。\n"
        "        command = translator.pop_pending_manual_track_change()\n"
        '        if command == "previous":\n'
        "            return\n"
        '        if command != "next" and translator.get_single_state() == "oneshot":\n'
        '            translator.set_single_state("0")\n'
        "            self.core.tracklist.set_single(False).get()\n"
        '        if translator.get_consume_state() == "oneshot":\n'
        '            translator.set_consume_state("0")\n'
        "            self.core.tracklist.set_consume(False).get()\n"
    )
    a = a.replace(old_revert, new_revert, 1)
    open(ap, "w").write(a)
    print(
        "patched actor.py: _revert_oneshot()がnext/previous由来かを区別し、"
        "singleは自然終了時のみ・consumeはpreviousでは戻さないよう修正"
    )
