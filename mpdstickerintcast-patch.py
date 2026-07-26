# mpdstickerfind-patch.py が追加した `_mpd_sticker_as_int()` (sticker find の
# eq/lt/gt 整数比較 と sort value_int で使用) は Python の `int(value)` を素直に
# `try/except ValueError: return 0` しているだけだが、実MPD本体
# (MusicPlayerDaemon/MPD、gh rawでsrc/sticker/Database.cxxを確認) は同じ変換を
# SQLite の `CAST(value AS INT)` (STICKER_SQL_FIND_EQ_INT等のSQL文字列、および
# `sort value_int` の `ORDER BY CAST(value AS INT)`) で行っており、両者の変換規則は
# 異なる。SQLiteのCAST(TEXT AS INTEGER)は「先頭の空白→任意の符号→1桁以上の数字」
# という前置数値プレフィックスだけを読み取り、その直後に非数字文字が続いても
# エラーにはせずそこまでの数値を返す(実機sqlite3で検証: CAST('42abc' AS INTEGER)=42、
# CAST('-3.9' AS INTEGER)=-3、CAST('  12.5  ' AS INTEGER)=12、数字が全く無ければ0
# (CAST('abc' AS INTEGER)=0)、64bit符号付き整数の範囲外は上下限にクランプされる
# (CAST('99999999999999999999' AS INTEGER)=9223372036854775807))。一方
# Pythonの`int()`は前置プレフィックスの解釈ができず全体が厳密な整数表記でなければ
# ValueErrorになるため、sticker値が"5abc"のような(スティッカーはクライアントが
# 任意の文字列を書き込めるため単位付き数値等が現実にありうる)前置数値+ゴミ文字列
# だと本来のCAST結果(5)ではなく一律0として扱われ、`sticker find ... NAME eq/lt/gt
# VALUE`のフィルタ結果や`sort value_int`の並び順が実MPDと食い違う不具合を修正。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "_MPD_STICKER_INT_RE"
if MARKER in s:
    print("sticker value_int CAST-compatible parsing already present, skip")
else:
    old_import = "import sqlite3\n"
    assert s.count(old_import) == 1, f"old_import count={s.count(old_import)}"
    new_import = "import re\n" + old_import
    s = s.replace(old_import, new_import, 1)

    old_as_int = (
        "def _mpd_sticker_as_int(value):\n"
        "    try:\n"
        "        return int(value)\n"
        "    except ValueError:\n"
        "        return 0\n"
    )
    assert s.count(old_as_int) == 1, f"old_as_int count={s.count(old_as_int)}"

    new_as_int = (
        '_MPD_STICKER_INT_RE = re.compile(r"^[ \\t\\r\\n\\f\\v]*([+-]?[0-9]+)")\n'
        "_MPD_STICKER_INT_MIN = -9223372036854775808\n"
        "_MPD_STICKER_INT_MAX = 9223372036854775807\n"
        "\n"
        "\n"
        "def _mpd_sticker_as_int(value):\n"
        "    match = _MPD_STICKER_INT_RE.match(value)\n"
        "    if match is None:\n"
        "        return 0\n"
        "    result = int(match.group(1))\n"
        "    if result > _MPD_STICKER_INT_MAX:\n"
        "        return _MPD_STICKER_INT_MAX\n"
        "    if result < _MPD_STICKER_INT_MIN:\n"
        "        return _MPD_STICKER_INT_MIN\n"
        "    return result\n"
    )
    s = s.replace(old_as_int, new_as_int, 1)

    open(p, "w").write(s)
    print(
        "patched stickers.py: _mpd_sticker_as_int を実MPDのSQLite "
        "CAST(value AS INT)互換の前置数値プレフィックス解析に変更"
    )
