# 共有レンジパーサ `protocol.RANGE()` (protocol/__init__.py) と兄弟の
# `_mpd_parse_window()` (protocol/music_db.py) が、コロンの後ろが完全な
# 空文字列ではなく「空白文字だけ」の場合 (例: `"5: "`) を、実MPDが拒否する
# べきところを黙って open-ended レンジとして受理してしまう不具合。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実MPD本体 (gh raw で `src/protocol/ArgParser.cxx` の
# `ParseCommandArgRange()` を確認):
#   if (*test == ':') {
#       value = strtol(++test, &test2, 10);
#       if (*test2 != '\0')
#           throw MakeArgError("Integer or range expected", s);
#       if (test == test2)
#           return RangeArg::OpenEnded(range.start);
#       ...
#   }
# `strtol()` はC標準通り先頭の空白をスキップして数値変換を試みるが、
# 数値が1文字も読めなかった場合 `endptr` には「変換開始前の元のポインタ」
# (=コロン直後の位置、空白を含む) が入る(libc `strtol`を`ctypes`経由で
# 実測して確認: 入力`" "`に対し`endptr`はオフセット0=コロン直後の位置の
# まま、`*endptr == ' '`)。よって `"5: "`(コロンの後ろが空白のみ)は
# `test2`がコロン直後の空白を指したまま`*test2 != '\0'`が真になり、
# `test == test2`(=open-ended)のチェックに到達する前に
# `ACK Integer or range expected` で拒否される。open-endedとして受理
# されるのは、コロンの直後が本当に何も無い(文字列末尾)場合、すなわち
# `strtol`が呼ばれた瞬間に`test2`がコロン直後の`'\0'`を指し
# `*test2 == '\0'`かつ`test == test2`が成立する、真に空の`"5:"`だけ。
#
# mopidy_mpd側の `RANGE()`(protocol/__init__.py) は
# `if stop.strip():`、`_mpd_parse_window()`(music_db.py) は
# `end_s = end_s.strip(); if end_s:` という形で、コロン後の文字列を
# 一旦 `.strip()` してから truthy 判定している。このため `"5: "` は
# `.strip()`後に空文字列になり、どちらも「open-ended」(`stop = None`
# / `end = None`)へ倒れてしまう — 実MPDなら拒否すべき入力を黙って
# 受理してしまう。BACKLOG.md全体を`stop.strip`/`end_s.strip`/
# `whitespace-only`/`空白のみ`/`trailing whitespace`/
# `Integer or range expected`/`window "5: "`で検索し、この
# 空白のみ残余ケースは既存項目(mpdstrictnumparse-patch.py=全角数字等の
# 非ASCII文字、mpduintmax-patch.py=UINT32上限超過)とは別軸の不具合で
# 既存項目に含まれないことを確認済み。
#
# 修正: 両関数とも、コロン後の残り文字列を `.strip()` した「後」の値で
# truthy判定するのをやめ、`.strip()`していない元の文字列そのもので
# 判定する(`if stop:` / `if end_s:` (strip前))。非空だが空白のみの
# 残余は、そのまま(strip前の値で)後段の `UINT()` へ渡され、
# `UINT()`のASCII限定正規表現(mpdstrictnumparse-patch.py)が空白を
# 数字と認めず`ValueError`を送出することで正しく拒否される。
# 真に空の`"5:"`/`"5"`はstrip前後で変わらず空文字列のままなので
# 既存のopen-ended/単一要素挙動に回帰は無い。

p_protocol = "mopidy_mpd/protocol/__init__.py"
s_protocol = open(p_protocol).read()

OLD_RANGE = (
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

NEW_RANGE = (
    "def RANGE(value):  # noqa: N802\n"
    '    """Convert a single integer or range spec into a slice\n'
    "\n"
    "    ``n`` should become ``slice(n, n+1)``\n"
    "    ``n:`` should become ``slice(n, None)``\n"
    "    ``n:m`` should become ``slice(n, m)`` and ``m >= n`` must hold\n"
    "    ``-1`` (bare, no colon) should become ``slice(0, None)`` for\n"
    "    compatibility with older MPD versions/clients (ncmpc, mpc)\n"
    "    A colon followed by whitespace-only content (e.g. ``5: ``) is\n"
    "    NOT open-ended (real MPD's strtol() only treats a truly empty\n"
    "    remainder as open-ended) and must fail via UINT().\n"
    '    """\n'
    '    if value == "-1":\n'
    "        return slice(0, None)\n"
    '    if ":" in value:\n'
    '        start, stop = value.split(":", 1)\n'
    "        start = UINT(start)\n"
    "        if stop:\n"
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

MARKER_RANGE = "whitespace-only content"
if MARKER_RANGE in s_protocol:
    print("RANGE() 空白のみ残余ガード already patched, skip")
else:
    assert s_protocol.count(OLD_RANGE) == 1, f"OLD_RANGE count={s_protocol.count(OLD_RANGE)}"
    s_protocol = s_protocol.replace(OLD_RANGE, NEW_RANGE, 1)
    open(p_protocol, "w").write(s_protocol)
    print(
        "patched protocol/__init__.py: RANGE()がコロン後が空白のみの残余"
        "(例: \"5: \")を黙ってopen-endedとして受理してしまう不具合を修正"
    )

p_musicdb = "mopidy_mpd/protocol/music_db.py"
s_musicdb = open(p_musicdb).read()

OLD_WINDOW = '''    if ":" not in value:
        start = _uint(value)
        return slice(start, start + 1)
    start_s, end_s = value.split(":", 1)
    start = _uint(start_s)
    end_s = end_s.strip()
    if end_s:
        end = _uint(end_s)
        if end < start:
            raise exceptions.MpdArgError(f"Invalid window: {value}")
    else:
        end = None
    return slice(start, end)
'''

NEW_WINDOW = '''    if ":" not in value:
        start = _uint(value)
        return slice(start, start + 1)
    start_s, end_s = value.split(":", 1)
    start = _uint(start_s)
    if end_s:
        end = _uint(end_s)
        if end < start:
            raise exceptions.MpdArgError(f"Invalid window: {value}")
    else:
        end = None
    return slice(start, end)
'''

MARKER_WINDOW = "start_s, end_s = value.split"
if MARKER_WINDOW in s_musicdb and "end_s.strip()" not in s_musicdb:
    print("_mpd_parse_window() 空白のみ残余ガード already patched, skip")
else:
    assert s_musicdb.count(OLD_WINDOW) == 1, f"OLD_WINDOW count={s_musicdb.count(OLD_WINDOW)}"
    s_musicdb = s_musicdb.replace(OLD_WINDOW, NEW_WINDOW, 1)
    open(p_musicdb, "w").write(s_musicdb)
    print(
        "patched music_db.py: _mpd_parse_window()がコロン後が空白のみの"
        "残余を黙ってopen-endedとして受理してしまう不具合を修正"
    )
