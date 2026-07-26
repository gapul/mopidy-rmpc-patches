# mopidy_mpd/protocol/current_playlist.py の `move`/`shuffle`/`swap` (raw
# position/range 指定の系統。`moveid`/`swapid` はtlid経由で常に実在する位置しか
# 渡らないため元々無害) が、範囲外の POS/START:END を渡されても実際には何も
# せずに `OK` を返してしまう不具合。
#
# 原因: これらのハンドラは `context.core.tracklist.move(...)` /
# `context.core.tracklist.shuffle(...)` の戻り値 (pykka の Future) に対し
# 一度も `.get()` を呼んでいない (mopidy-mpd 本家からしてこの書き方で、戻り値を
# 使わないから素通りしていたと見られる)。mopidy/core/tracklist.py の
# `move()`/`shuffle()` は範囲外の start/end/to_position に対し裸の
# `AssertionError` を投げる実装だが、`.get()` を呼ばない限り pykka の Future は
# 例外を握ったまま誰にも再送出されず、`mopidy_mpd/dispatcher.py` の
# `_catch_mpd_ack_errors_filter`(`exceptions.MpdAckError` のみ捕捉) にも
# 引っかからないため、mopidy.log にすら記録されず握り潰される。結果として
# キューは一切変化していないのに MPD クライアントには `OK` が返る
# (rmpc でキュー末尾を越える位置へドラッグ移動/シャッフル/swap した場合などに
# 実際に起こりうる、サイレントな操作失敗)。
#
# 実際に dev mopidy(6601, ytmusic 実アカウント) で 2曲キューに対し
# `move "99" "0"` / `swap "0" "99"` / `shuffle "0:99"` を送って確認済み: 全て
# `OK` が返るが `playlistinfo` のPos/Id/曲順は一切変化せず、mopidy.log にも
# AssertionError は一切出力されない (パッチ前の実際の不具合として再現確認)。
#
# 修正: `.get()` を呼んで実行を同期化し、`AssertionError` を実 MPD 同様の
# `ACK ... Bad song index` (`delete()` と同じ文言) に変換する。`swap` は
# 追加で、2回の `move()` 呼び出しの前に長さチェックを行い範囲外を弾く
# (`songpos1 == songpos2` は実害の無い自分自身への swap なので no-op で OK)。
# `command` は明示指定せず、`dispatcher._call_handler` が
# `exc.command is None` の場合に実際にクライアントが送ったコマンド名
# (`move`/`shuffle`/`swap`) を自動補完する既存の仕組みに委ねる。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

MARKER = "except AssertionError:\n        raise exceptions.MpdArgError(\"Bad song index\")"
if MARKER in s:
    print("move/shuffle/swap race already patched, skip")
else:
    # move (move_range)
    old_move = (
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        "        end = context.core.tracklist.get_length().get()\n"
        "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
        "    context.core.tracklist.move(start, end, to_position)\n"
    )
    assert s.count(old_move) == 1, f"old_move count={s.count(old_move)}"
    new_move = (
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        "        end = context.core.tracklist.get_length().get()\n"
        "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
        "    try:\n"
        "        context.core.tracklist.move(start, end, to_position).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_move, new_move, 1)

    # moveid
    old_moveid = (
        '    tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()\n'
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    position = context.core.tracklist.index(tl_tracks[0]).get()\n"
        "    to_position = _mpd_resolve_move_to(\n"
        "        context, to, position, position + 1\n"
        "    )\n"
        "    context.core.tracklist.move(position, position + 1, to_position)\n"
    )
    assert s.count(old_moveid) == 1, f"old_moveid count={s.count(old_moveid)}"
    new_moveid = (
        '    tl_tracks = context.core.tracklist.filter({"tlid": [tlid]}).get()\n'
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    position = context.core.tracklist.index(tl_tracks[0]).get()\n"
        "    to_position = _mpd_resolve_move_to(\n"
        "        context, to, position, position + 1\n"
        "    )\n"
        "    try:\n"
        "        context.core.tracklist.move(position, position + 1, to_position).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_moveid, new_moveid, 1)

    # shuffle
    old_shuffle = (
        "    if songrange is None:\n"
        "        start, end = None, None\n"
        "    else:\n"
        "        start, end = songrange.start, songrange.stop\n"
        "    context.core.tracklist.shuffle(start, end)\n"
    )
    assert s.count(old_shuffle) == 1, f"old_shuffle count={s.count(old_shuffle)}"
    new_shuffle = (
        "    if songrange is None:\n"
        "        start, end = None, None\n"
        "    else:\n"
        "        start, end = songrange.start, songrange.stop\n"
        "    try:\n"
        "        context.core.tracklist.shuffle(start, end).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_shuffle, new_shuffle, 1)

    # swap
    old_swap = (
        "    if songpos2 < songpos1:\n"
        "        songpos1, songpos2 = songpos2, songpos1\n"
        "    context.core.tracklist.move(songpos1, songpos1 + 1, songpos2)\n"
        "    context.core.tracklist.move(songpos2 - 1, songpos2, songpos1)\n"
    )
    assert s.count(old_swap) == 1, f"old_swap count={s.count(old_swap)}"
    new_swap = (
        "    length = context.core.tracklist.get_length().get()\n"
        "    if songpos1 >= length or songpos2 >= length:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
        "    if songpos1 == songpos2:\n"
        "        return\n"
        "    if songpos2 < songpos1:\n"
        "        songpos1, songpos2 = songpos2, songpos1\n"
        "    try:\n"
        "        context.core.tracklist.move(songpos1, songpos1 + 1, songpos2).get()\n"
        "        context.core.tracklist.move(songpos2 - 1, songpos2, songpos1).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    s = s.replace(old_swap, new_swap, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: move/moveid/shuffle/swap の範囲外指定が"
        "サイレントにOKを返す不具合を修正 (.get()で例外を伝播しACK Bad song indexへ変換)"
    )
