# mopidy_mpd/protocol/__init__.py の共有レンジパーサ `protocol.RANGE()` が、
# 実MPD本体が後方互換のため受理する裸の(コロン無し) `"-1"` (「リスト全体」を
# 意味する) を一切考慮せず、`UINT("-1")` の `ValueError("Only positive
# numbers are allowed")` で拒否してしまう不具合。TODO全項目消化済みのため
# 自走エージェントが(general-purposeサブエージェントへの調査委任を経て)
# 新規発見。
#
# 実MPD本体 (gh raw で `src/protocol/ArgParser.cxx` の
# `ParseCommandArgRange()` を確認) はコロンを含まない裸の整数をまず
# `strtol()` でパースし、`value == -1 && *test == '\0'` (コロンで続かない、
# 文字列全体が厳密に"-1"の場合のみ)を「旧バージョンMPDとの互換性のため、
# "-1"はリスト全体を表示する」という特別分岐で `RangeArg::All()`
# (`{start:0, end:UINT_MAX}` の open-ended レンジ)として受理する
# (コメント原文: "compatibility with older MPD versions: specifying '-1'
# makes MPD display the whole list")。この共有パーサは
# `delete`/`move`/`shuffle`/`prio` (QueueCommands.cxx `args.ParseRange()`/
# `ParseCommandArgRange()`直接呼び出し) と `listplaylist`/`listplaylistinfo`/
# `playlistdelete`/`playlistmove` (PlaylistCommands.cxx 同様)
# の唯一の共有レンジ構文であり、mopidy_mpd側でもこれら全てが
# `protocol.RANGE`をバリデータ/直接呼び出しとして共有している
# (current_playlist.py の `delete`/`move_range`/`shuffle`/`prio`、
# stored_playlists.py の `listplaylist`/`listplaylistinfo`/`load`/
# `playlistdelete`/`playlistmove`)。
#
# 一方 `playlistinfo` (current_playlist.py) は元々 `parameter == "-1"` を
# `RANGE()`呼び出し以前に自前で特別扱いしており(ncmpc/mpc由来の既知の互換
# 挙動として docstring にも明記済み)、本パッチはその手前で短絡する既存分岐
# には触れず、共有 `RANGE()` 本体にも同じ特別扱いを一般化するのみ
# (playlistinfoの挙動に変化なし)。
#
# `move`/`playlistmove` の `FROM` に対して実MPDは `IsOpenEnded()`
# (open-ended レンジ、"-1"はまさにこれに該当) を `ACK Open-ended range not
# supported` で明示的に拒否する (PlaylistCommands.cxx
# `handle_playlistmove`、QueueCommands.cxx 経由の `handle_move`) が、
# mopidy_mpdの`move_range()`/`playlistmove()`は元々open-ended(`"N:"`)
# 自体を既に拒否せず受理する実装になっており(`end is None`を
# `get_length()`で解決するフォールバック処理が既存)、本パッチは
# その既存の(real MPDとは別の)open-ended許容ポリシーを変更せず、
# `"-1"`を既存の`"0:"`(open-ended)と全く同じslice(0, None)へ正規化する
# だけなので新たな非整合は生まない(既存挙動に`"-1"`という別名が
# 増えるだけ)。
#
# BACKLOG.md/nix/lib/mopidy-env.nix全体を`RANGE(`/`"-1"`で検索し、
# 本件(裸の"-1"互換分岐)は既存のmpdrangeempty-patch.py
# (start==stop空範囲の緩和、別の不具合)以外に触れられていないことを確認済み。
#
# 実機再現 (dev mopidy 6601、キューに複数曲): `delete "-1"` →
# `ACK [2@0] {delete} incorrect arguments` (実MPDなら`OK`、キュー全体を削除)。
# `shuffle "-1"` も同様に ACK incorrect arguments になる。
#
# 修正方針: `RANGE()` の先頭に `value == "-1"` の特別分岐を追加し
# `slice(0, None)` を返す(コロンを含む `"-1:5"` 等はこの分岐に一致せず
# 従来通りエラーのまま、実MPDの`*test == '\0'`条件と同じ厳密一致)。

p_protocol = "mopidy_mpd/protocol/__init__.py"

s_protocol = open(p_protocol).read()

NEW_RANGE = (
    "def RANGE(value):  # noqa: N802\n"
    '    """Convert a single integer or range spec into a slice\n'
    "\n"
    "    ``n`` should become ``slice(n, n+1)``\n"
    "    ``n:`` should become ``slice(n, None)``\n"
    "    ``n:m`` should become ``slice(n, m)`` and ``m >= n`` must hold\n"
    "    ``-1`` (bare, no colon) should become ``slice(0, None)`` for\n"
    "    compatibility with older MPD versions/clients (ncmpc, mpc)\n"
    '    """\n'
    '    if value == "-1":\n'
    "        return slice(0, None)\n"
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
    print("protocol.RANGE() -1互換ガード already patched, skip")
else:
    OLD_RANGE = (
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
    assert s_protocol.count(OLD_RANGE) == 1, f"OLD_RANGE count={s_protocol.count(OLD_RANGE)}"
    s_protocol = s_protocol.replace(OLD_RANGE, NEW_RANGE, 1)
    open(p_protocol, "w").write(s_protocol)
    print(
        "patched protocol/__init__.py: RANGE()が裸の\"-1\"(旧MPD互換、"
        "リスト全体を意味する)を一律ValueErrorにしてしまう不具合を修正 "
        "(\"-1\"はslice(0, None)としてパース成功へ)"
    )
