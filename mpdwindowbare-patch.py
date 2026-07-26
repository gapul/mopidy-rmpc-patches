# find/search/findadd/searchadd/list/playlistfind/playlistsearch/searchplaylist/
# sticker find が共有する `window` 修飾子パーサ `_mpd_parse_window()`
# (music_db.py, mpdwindow-patch.py で新設) が、コロンを含まない裸の数値
# (`window "5"` 等) を一律 `ACK Invalid window: 5` で拒否してしまう不具合。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実MPD本体 (gh raw で `src/protocol/ArgParser.cxx` の
# `ParseCommandArgRange()` を確認、`window` 引数は
# `src/command/DatabaseCommands.cxx`/`PlaylistCommands.cxx` の両方で
# `args.ParseRange(...)` 経由でこの同じ関数を呼ぶ) はコロンを含まない
# 裸の整数をまず `strtol()` でパースし、
#   - 文字列全体が厳密に `"-1"` (`value == -1 && *test == '\0'`) の場合のみ
#     「旧バージョンMPDとの互換性のため、"-1"はリスト全体を表示する」という
#     特別分岐で `RangeArg::All()` (`slice(0, None)` 相当) を返す
#     (コメント原文: "compatibility with older MPD versions: specifying
#     '-1' makes MPD display the whole list")
#   - それ以外の非負の裸の数値は `RangeArg::Single(value)`
#     (`{start: value, end: value + 1}`、`slice(value, value + 1)` 相当)
#     を返す
# という2つの分岐を持つ。つまり `window "5"` は本来 `slice(5, 6)`
# (単一要素) として受理されるべきで、ACKになるべきではない。
#
# mopidy_mpd側では全く同じ real MPD 関数 (`ParseCommandArgRange`) が
# バックエンドとなる別のレンジ構文 `delete`/`move`/`shuffle`/`prio`/
# `playlistdelete`/`playlistmove` 等の共有パーサ `protocol.RANGE()`
# (protocol/__init__.py) では、裸の `"-1"` 分岐は既に
# mpdrangeminusone-patch.py で、裸の数値 (`n` -> `slice(n, n+1)`) は
# 元々の実装時点から両方とも正しく実装されている
# (`RANGE()`: `else: start = UINT(value); stop = start + 1`)。
# しかし `window` 修飾子専用に後発で新設された `_mpd_parse_window()`
# (music_db.py) だけは、コロンの有無で即座に必須/エラーとする実装のまま
# この2分岐が一切移植されていなかった。
#
# BACKLOG.md全体を `_mpd_parse_window`/`Invalid window` で検索し、
# mpdwindow-patch.py導入時の検証記録 (「`window "5"` は `ACK Invalid
# window: ...` が期待通りの正しい挙動」) が唯一の言及であることを確認済み
# (real MPD本体のC++実装を確認せず、`window {START:END}` というプロトコル
# 文書の書式表記だけを根拠にした誤った結論だった)。`_mpd_parse_window` の
# 呼び出し元 (`find`/`search`/`list`/`playlistfind`/`playlistsearch`/
# `searchplaylist`/`sticker find`/`findadd`/`searchadd`) はいずれもこの
# 共有関数を import して呼ぶだけで関数本体を編集する patch は他に無い
# (`grep -l "_mpd_parse_window" *.py` で呼び出し元6ファイルを確認済み、
# いずれも呼び出しのみで本体無編集)。
#
# 実機再現 (dev mopidy 6601): `findadd "(any contains \"yoasobi\")" window
# "0"` (修正前) -> `ACK [2@0] {findadd} Invalid window: 0`
# (実MPDなら最初の1件だけ追加される単一要素レンジとして受理されるべき)。
# `window "-1"` も同様に ACK になっていた (実MPDなら旧互換でリスト全体)。
#
# 修正: `_mpd_parse_window()` の先頭に real MPD の2分岐 (裸の `"-1"` ->
# `slice(0, None)`、コロン無しのその他の非負整数 -> `slice(n, n+1)`) を
# 追加。コロンを含む既存の `START:END`/`START:` 構文は無変更。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

OLD_FUNC = '''def _mpd_parse_window(value):
    """`window START:END` の値部分を slice に変換する。0-based, END は非包含。
    END 省略 (`START:`) は open-ended。書式不正/非数値/負値は MpdArgError。
    """
    if ":" not in value:
        raise exceptions.MpdArgError(f"Invalid window: {value}")
    start_s, end_s = value.split(":", 1)
    if not start_s.isdigit():
        raise exceptions.MpdArgError(f"Invalid window: {value}")
    start = int(start_s)
    end_s = end_s.strip()
    if end_s:
        if not end_s.isdigit():
            raise exceptions.MpdArgError(f"Invalid window: {value}")
        end = int(end_s)
        if end < start:
            raise exceptions.MpdArgError(f"Invalid window: {value}")
    else:
        end = None
    return slice(start, end)
'''

NEW_FUNC = '''def _mpd_parse_window(value):
    """`window START:END` の値部分を slice に変換する。0-based, END は非包含。
    END 省略 (`START:`) は open-ended。書式不正/非数値/負値は MpdArgError。
    コロンを含まない裸の `"-1"` は実MPD (`ParseCommandArgRange()`) の
    旧バージョン互換分岐と同じくリスト全体 (`slice(0, None)`) を意味する。
    それ以外のコロン無し非負整数は単一要素レンジ (`slice(n, n + 1)`、
    実MPDの `RangeArg::Single()` 相当) を意味する。
    """
    if value == "-1":
        return slice(0, None)
    if ":" not in value:
        if not value.isdigit():
            raise exceptions.MpdArgError(f"Invalid window: {value}")
        start = int(value)
        return slice(start, start + 1)
    start_s, end_s = value.split(":", 1)
    if not start_s.isdigit():
        raise exceptions.MpdArgError(f"Invalid window: {value}")
    start = int(start_s)
    end_s = end_s.strip()
    if end_s:
        if not end_s.isdigit():
            raise exceptions.MpdArgError(f"Invalid window: {value}")
        end = int(end_s)
        if end < start:
            raise exceptions.MpdArgError(f"Invalid window: {value}")
    else:
        end = None
    return slice(start, end)
'''

MARKER = "実MPDの `RangeArg::Single()`"
if MARKER in s:
    print("window裸数値/裸-1互換 already patched, skip")
else:
    assert s.count(OLD_FUNC) == 1, f"OLD_FUNC count={s.count(OLD_FUNC)}"
    s = s.replace(OLD_FUNC, NEW_FUNC, 1)
    open(p, "w").write(s)
    print(
        "patched music_db.py: _mpd_parse_window()がコロン無しの裸の数値/"
        "裸の\"-1\"を一律ACKで拒否してしまう不具合を修正 "
        "(実MPD ParseCommandArgRange()の単一要素レンジ/旧互換分岐を移植)"
    )
