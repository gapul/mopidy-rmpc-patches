# mopidy_mpd/protocol/__init__.py の共有レンジパーサ `protocol.RANGE()` が
# `START:END` の `START == END` (空だが不正ではない範囲、実MPD仕様の
# well-formed empty range) を一律 `ValueError("End must be larger than
# start")` (→呼び出し元で `ACK incorrect arguments` かセッション切断) にして
# しまう不具合。TODO全項目消化済みのため自走エージェントがmopidy_mpdの
# 共有ヘルパー層を再調査して新規発見。
#
# 実MPD (musicpd.org protocol、および upstream MPD `src/protocol/RangeArg.hxx`
# の `IsWellFormed()` = `start <= end`) は `START == END` を「0件を指す
# 空範囲」として正当に受理する (例: 3曲キューに対する `delete "0:0"` は
# 何も削除せず `OK` を返す no-op)。対して `protocol.RANGE()` は
# `start >= stop` を丸ごとエラー扱いにしており、`start == stop` の
# well-formed な空範囲まで巻き込んで拒否してしまう。
#
# `RANGE()` は `delete`/`move`/`shuffle` (current_playlist.py、デコレータ
# 引数バリデータ経由)、`playlistinfo`/`prio` (同ファイル、関数内で手動呼び出し
# しValueErrorをACK incorrect argumentsへ変換)、`listplaylist`/
# `listplaylistinfo`/`load`/`playlistdelete`/`playlistmove`
# (stored_playlists.py) の唯一の共有パース経路であり、いずれのコマンドも
# `START:END` に `START == END` を渡すと (パース自体がここで失敗するため)
# ハンドラ本体には到達せず一律ACKになる。既存の `mpddeleteboundary-patch.py`/
# `mpdprioboundary-patch.py` は「開区間 `start:` が境界(`start==キュー長`)に
# 一致するケース」というRANGE()通過後の別の境界問題を修正したものであり、
# 本件 (`N:N` という閉区間そのものがRANGE()のパース時点で拒否される) とは
# 別のコードパス・別の不具合。BACKLOG.md/nix/lib/mopidy-env.nix全体を
# `RANGE(` で検索してもRANGE()自体を再定義した既存パッチは無いことを確認済み。
#
# 実機再現 (dev mopidy 6601、キュー内に複数曲): `delete "0:0"` →
# `ACK [2@0] {delete} incorrect arguments` (実MPDなら`OK`、無変更)。
# `playlistinfo "0:0"` も同様に `ACK [2@0] {playlistinfo} incorrect
# arguments` (実MPDなら`OK`のみ、0件のトラック一覧)。
#
# 修正方針: `RANGE()` 自体の判定を `start >= stop` から `start > stop` へ
# 緩和し、`start == stop` (well-formed空範囲) をパース成功させる。
# これだけでは済まない箇所が2つあることを個別に実機コードリーディングで
# 確認し同時に修正する:
#
# (1) `move_range()` (current_playlist.py): `mopidy/core/tracklist.py` の
#     `move(start, end, to_position)` は `if start == end: end += 1` という
#     独自の特殊扱いを持ち (mopidy core自体はパッチ対象外のため変更不可)、
#     RANGE()を緩和しただけだと `move "0:0" N` が「0曲を動かす」ではなく
#     「positionの曲を1曲動かす」というサイレントな誤動作に化けてしまう
#     (ACKで拒否されていた状態より悪化する新規のサイレントバグ)。
#     `_mpd_resolve_move_to()` によるTO解決自体は `start==end` でも
#     (`new_length = queue_length - (end-start)` が単に無変更長になるだけで)
#     正しく動作するため、TO解決・検証は従来通り行った上で
#     `context.core.tracklist.move()` の実呼び出しだけを`start==end`のとき
#     skipするガードを追加する。
#
# (2) `shuffle()` (current_playlist.py): `mopidy/core/tracklist.py` の
#     `shuffle(start, end)` は独自に `if start is not None and end is not
#     None and start >= end: raise AssertionError` を持ち (これもmopidy core
#     側でパッチ対象外)、RANGE()緩和後に `shuffle "0:0"` を送ると
#     このAssertionErrorが`except AssertionError`で捕捉され`ACK Bad song
#     index`になってしまう (実MPDなら0曲のシャッフルはno-opでOK)。
#     `start == end` のときは`context.core.tracklist.shuffle()`呼び出し自体を
#     skipし直接returnするガードを追加する。
#
# なお `delete`/`playlistinfo`/`prio`/`listplaylist`/`listplaylistinfo`/
# `playlistdelete`/`playlistmove` は素のPythonリストスライス
# (`list[start:end]`) や既存の空リストチェック (mpddeleteboundary-patch.py/
# mpdprioboundary-patch.py) だけで`start==end`を正しくno-op扱いできており、
# RANGE()の緩和のみで実MPDと同じ挙動になることをソースを読んで確認した
# (`load`のPOSITION解決 `_mpd_resolve_load_position`もTOと同様に長さベースの
# 計算のみで`playlist_slice`の中身には依存しないため対象外)。

p_protocol = "mopidy_mpd/protocol/__init__.py"
p_cp = "mopidy_mpd/protocol/current_playlist.py"

s_protocol = open(p_protocol).read()

NEW_RANGE = (
    "def RANGE(value):  # noqa: N802\n"
    '    """Convert a single integer or range spec into a slice\n'
    "\n"
    "    ``n`` should become ``slice(n, n+1)``\n"
    "    ``n:`` should become ``slice(n, None)``\n"
    "    ``n:m`` should become ``slice(n, m)`` and ``m >= n`` must hold\n"
    '    """\n'
    '    if ":" in value:\n'
    '        start, stop = value.split(":", 1)\n'
    "        start = UINT(start)\n"
    "        if stop.strip():\n"
    "            stop = UINT(stop)\n"
    "            if start > stop:\n"
    '                raise ValueError("End must not be smaller than start")\n'
    "        else:\n"
    "            stop = None\n"
    "    else:\n"
    "        start = UINT(value)\n"
    "        stop = start + 1\n"
    "    return slice(start, stop)\n"
)

if NEW_RANGE in s_protocol:
    print("protocol.RANGE() start==stop guard already patched, skip")
else:
    OLD_RANGE = (
        "def RANGE(value):  # noqa: N802\n"
        '    """Convert a single integer or range spec into a slice\n'
        "\n"
        "    ``n`` should become ``slice(n, n+1)``\n"
        "    ``n:`` should become ``slice(n, None)``\n"
        "    ``n:m`` should become ``slice(n, m)`` and ``m > n`` must hold\n"
        '    """\n'
        '    if ":" in value:\n'
        '        start, stop = value.split(":", 1)\n'
        "        start = UINT(start)\n"
        "        if stop.strip():\n"
        "            stop = UINT(stop)\n"
        "            if start >= stop:\n"
        '                raise ValueError("End must be larger than start")\n'
        "        else:\n"
        "            stop = None\n"
        "    else:\n"
        "        start = UINT(value)\n"
        "        stop = start + 1\n"
        "    return slice(start, stop)\n"
    )
    assert s_protocol.count(OLD_RANGE) == 1, f"OLD_RANGE count={s_protocol.count(OLD_RANGE)}"
    s_protocol = s_protocol.replace(OLD_RANGE, NEW_RANGE, 1)
    open(p_protocol, "w").write(s_protocol)
    print(
        "patched protocol/__init__.py: RANGE()がSTART==END(well-formedな"
        "空範囲)を一律ValueErrorにしてしまう不具合を修正 (start>stopのみ"
        "エラー、start==stopはslice(start,start)としてパース成功へ)"
    )

s_cp = open(p_cp).read()

NEW_MOVE = (
    "    start = songrange.start\n"
    "    end = songrange.stop\n"
    "    if end is None:\n"
    "        end = context.core.tracklist.get_length().get()\n"
    "    version = context.core.tracklist.get_version().get()\n"
    "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
    "    if start == end:\n"
    "        return\n"
    "    try:\n"
    "        context.core.tracklist.move(start, end, to_position).get()\n"
    "        if context.core.tracklist.get_version().get() != version + 1:\n"
    '            raise exceptions.MpdArgError("Bad song index")\n'
    "    except AssertionError:\n"
    '        raise exceptions.MpdArgError("Bad song index")\n'
)

if NEW_MOVE in s_cp:
    print("move_range() start==end no-op guard already patched, skip")
else:
    OLD_MOVE = (
        "    start = songrange.start\n"
        "    end = songrange.stop\n"
        "    if end is None:\n"
        "        end = context.core.tracklist.get_length().get()\n"
        "    version = context.core.tracklist.get_version().get()\n"
        "    to_position = _mpd_resolve_move_to(context, to, start, end)\n"
        "    try:\n"
        "        context.core.tracklist.move(start, end, to_position).get()\n"
        "        if context.core.tracklist.get_version().get() != version + 1:\n"
        '            raise exceptions.MpdArgError("Bad song index")\n'
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert s_cp.count(OLD_MOVE) == 1, f"OLD_MOVE count={s_cp.count(OLD_MOVE)}"
    s_cp = s_cp.replace(OLD_MOVE, NEW_MOVE, 1)
    print(
        "patched current_playlist.py: move()がstart==end(空範囲)のとき"
        "core.tracklist.move()の`start==end`特殊扱い(end+=1で1曲だけ動かして"
        "しまう)を誘発する不具合を修正 (0曲移動は core呼び出し自体をskipし"
        "no-opでOKへ)"
    )

NEW_SHUFFLE = (
    "    if songrange is None:\n"
    "        start, end = None, None\n"
    "    else:\n"
    "        start, end = songrange.start, songrange.stop\n"
    "    if start is not None and end is not None and start == end:\n"
    "        return\n"
    "    try:\n"
    "        context.core.tracklist.shuffle(start, end).get()\n"
    "    except AssertionError:\n"
    '        raise exceptions.MpdArgError("Bad song index")\n'
)

if NEW_SHUFFLE in s_cp:
    print("shuffle() start==end no-op guard already patched, skip")
else:
    OLD_SHUFFLE = (
        "    if songrange is None:\n"
        "        start, end = None, None\n"
        "    else:\n"
        "        start, end = songrange.start, songrange.stop\n"
        "    try:\n"
        "        context.core.tracklist.shuffle(start, end).get()\n"
        "    except AssertionError:\n"
        '        raise exceptions.MpdArgError("Bad song index")\n'
    )
    assert s_cp.count(OLD_SHUFFLE) == 1, f"OLD_SHUFFLE count={s_cp.count(OLD_SHUFFLE)}"
    s_cp = s_cp.replace(OLD_SHUFFLE, NEW_SHUFFLE, 1)
    print(
        "patched current_playlist.py: shuffle()がstart==end(空範囲)のとき"
        "core.tracklist.shuffle()のAssertionError(start>=endガード)を誘発し"
        "ACK Bad song indexにしてしまう不具合を修正 (0曲シャッフルはcore"
        "呼び出し自体をskipしno-opでOKへ)"
    )

open(p_cp, "w").write(s_cp)
