# current_playlist.py の `shuffle` が、範囲内に再生中の曲が含まれる場合でも
# 位置を一切固定せず全曲を無差別にシャッフルしてしまう不具合を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実MPD本体 (gh rawで src/queue/PlaylistEdit.cxx の playlist::Shuffle() を確認):
#
#   if (playing && current >= 0) {
#       unsigned current_position = queue.OrderToPosition(current);
#       if (range.Contains(current_position)) {
#           /* put current playing song first */
#           queue.SwapPositions(range.start, current_position);
#           ...
#           /* start shuffle after the current song */
#           range.start++;
#       }
#   }
#   queue.ShuffleRange(range.start, range.end);
#
# `playing` はプレイヤーが再生中/一時停止中(=停止していない)であることを示す
# フラグ (Playlist.hxx)。つまり実MPDは、再生中の曲が指定範囲に含まれる場合、
# 必ずその曲を範囲の先頭(range.start、既定は0)へスワップしてから、残りの
# 範囲だけをシャッフルする。再生中の曲の位置(song/songidのsong側)は
# shuffle実行後も常にrange.startに固定される仕様。
#
# mopidy_mpdの shuffle() (mpdmoveswaprace-patch.py/mpdrangeempty-patch.py適用後)
# は `context.core.tracklist.shuffle(start, end)` を呼ぶだけで、この固定処理を
# 一切行っていない。mopidy/core/tracklist.py の Tracklist.shuffle() も範囲内の
# 全曲(再生中の曲を含む)を無差別に random.shuffle() するのみ。
#
# 実機確認 (TCP 6601, mopidy-ytmusic実アカウント): searchaddで20曲キューに積み
# play "3" で再生開始後、引数なし shuffle を8回連続実行し毎回 status の song/
# songid を記録した結果、songid は常に同一(再生中の曲の同一性は保たれる)だが
# song(位置)は 14,16,17,9,19,16,11,14 とほぼ一様にランダムで、実MPD仕様が
# 保証する「常に0」には一致しなかった。
#
# rmpcはキュー画面で再生中の曲をハイライト/オートスクロールする際 status の
# song/songidに基づき位置を特定するため、shuffle直後に再生中の曲がキューの
# 任意の位置へランダムに飛ぶのは実MPDとの可観測なプロトコル差異。
#
# 修正: current_playlist.py の shuffle() に、範囲内(かつ再生中/一時停止中)に
# 現在の曲が含まれる場合、同ファイル内の既存 swap() (move()を2回呼ぶ既存の
# 位置交換ロジックをそのまま再利用) で range.start と入れ替えてから、
# range.start を1つ進めた上で core.tracklist.shuffle() を呼ぶ処理を追加。

sp = "mopidy_mpd/protocol/current_playlist.py"
s = open(sp).read()

MARKER = "# mpdshufflepin: pin currently playing song to range start"
if MARKER in s:
    print("shufflepin already patched, skip")
else:
    old_shuffle = (
        "    if start is not None and end is not None and start == end:\n"
        "        return\n"
        "    try:\n"
        "        context.core.tracklist.shuffle(start, end).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert s.count(old_shuffle) == 1, f"old_shuffle count={s.count(old_shuffle)}"
    new_shuffle = (
        "    if start is not None and end is not None and start == end:\n"
        "        return\n"
        "    try:\n"
        "        " + MARKER + "\n"
        "        range_start = start if start is not None else 0\n"
        "        range_end = (\n"
        "            end if end is not None else context.core.tracklist.get_length().get()\n"
        "        )\n"
        "        # 空/1曲レンジは実MPD同様 no-op で OK (shuffle(0,0) は mopidy core の\n"
        "        # assert start < end に当たり ACK Bad song index になるため)\n"
        "        if range_end - range_start <= 1:\n"
        "            return\n"
        "        if range_end - range_start >= 2:\n"
        "            state = context.core.playback.get_state().get()\n"
        "            if state != PlaybackState.STOPPED:\n"
        "                current_index = context.core.tracklist.index().get()\n"
        "                if (\n"
        "                    current_index is not None\n"
        "                    and range_start <= current_index < range_end\n"
        "                ):\n"
        "                    if current_index != range_start:\n"
        "                        swap(context, range_start, current_index)\n"
        "                    range_start += 1\n"
        "        context.core.tracklist.shuffle(range_start, range_end).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_shuffle, new_shuffle, 1)

    open(sp, "w").write(s)
    print(
        "patched current_playlist.py: shuffle()が再生中の曲をrangeの先頭へ"
        "固定してから残りをシャッフルするよう修正(実MPDのplaylist::Shuffle()と同挙動)"
    )
