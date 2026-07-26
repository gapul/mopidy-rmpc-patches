# find/search/findadd/searchadd/list/playlistfind/playlistsearch/searchplaylist/
# sticker find が共有する `window` 修飾子パーサ `_mpd_parse_window()`
# (music_db.py) が、数値部分の妥当性チェックに Python の `str.isdigit()` +
# 素の `int()` を使っており、実MPDの共有パーサが持つ2つの検証軸
# (ASCII数字限定・上限チェック) の両方を欠いている不具合。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# `str.isdigit()` はUnicode対応のため全角数字等も真になる
# (例: `"５".isdigit()` -> True, `int("５")` -> 5)。よって
# `window "５"` (全角5) が現状 `slice(5, 6)` として黙って受理されてしまう。
# また Python の `int()` は任意精度のため上限が無く、
# `window "99999999999999999999"` のような桁数だけ正しい巨大な数値も
# パースに成功し `slice()` を構築してしまう。
#
# 実MPD本体 (gh raw で `src/protocol/ArgParser.cxx` の
# `ParseCommandArgRange()` を確認) は各数値要素を `strtol(s, &test, 10)` で
# パースし、`test == s`(数字として1文字も消費できない = 全角数字などは
# ASCII基準で非数値)または末尾に余分な文字が残る場合は
# `ACK Integer or range expected` を返し、さらに
# `value > std::numeric_limits<int>::max()` の場合は
# `ACK Number too large` を返す。
#
# mopidy_mpd 側では全く同じ real MPD 関数 (`ParseCommandArgRange`) を
# 参照する兄弟パーサ `protocol.RANGE()` (protocol/__init__.py、
# `delete`/`move`/`shuffle`/`prio`等が使用) は、この2つの検証軸を
# 既に `UINT()` (mpdstrictnumparse-patch.py が ASCII限定正規表現
# `_MPD_STRICT_UINT_RE` を、mpduintmax-patch.py が上限 `_MPD_UINT_MAX`
# =0xFFFFFFFF チェックを追加済み) への委譲によって両方とも実装している。
# しかし `window` 修飾子専用の `_mpd_parse_window()` (mpdwindow-patch.py
# 新設、mpdwindowbare-patch.py がコロン無し裸数値/裸"-1"分岐を追加) だけは
# 独自に `str.isdigit()` + `int()` を直書きしており、`RANGE()` 経由の
# `UINT()` が持つこの2つの保護のどちらも受けていない。
#
# BACKLOG.md全体を `_mpd_parse_window`/`isdigit`/`UINT` で検索し、
# window修飾子について全角数字/上限超過の観点は既存項目に無いことを
# 確認済み。呼び出し元 (`find`/`search`/`list`/`playlistfind`/
# `playlistsearch`/`searchplaylist`/`sticker find`/`findadd`/`searchadd`) は
# いずれもこの共有関数を import して呼ぶだけで本体を編集する patch は
# mpdwindow-patch.py/mpdwindowbare-patch.py以外に無い
# (`grep -l "_mpd_parse_window" *.py` で確認済み)。
#
# 修正: `_mpd_parse_window()` の数値パース部分を素の `str.isdigit()`/`int()`
# から `protocol.UINT()` 呼び出し (ValueError捕捉 -> 既存の
# `MpdArgError(f"Invalid window: {value}")` へ変換) へ置き換え、
# `RANGE()` と同じASCII限定・上限チェックを共有させる。裸の `"-1"` 特別
# 分岐 (文字列完全一致) は数値パースを経由しないため無変更。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

OLD_FUNC = '''def _mpd_parse_window(value):
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

NEW_FUNC = '''def _mpd_parse_window(value):
    """`window START:END` の値部分を slice に変換する。0-based, END は非包含。
    END 省略 (`START:`) は open-ended。書式不正/非数値/負値は MpdArgError。
    コロンを含まない裸の `"-1"` は実MPD (`ParseCommandArgRange()`) の
    旧バージョン互換分岐と同じくリスト全体 (`slice(0, None)`) を意味する。
    それ以外のコロン無し非負整数は単一要素レンジ (`slice(n, n + 1)`、
    実MPDの `RangeArg::Single()` 相当) を意味する。
    数値部分は兄弟パーサ `protocol.RANGE()` と同じ `protocol.UINT()` で
    検証し、ASCII数字限定・上限 (0xFFFFFFFF) チェックを共有する。
    """
    if value == "-1":
        return slice(0, None)

    def _uint(token):
        try:
            return protocol.UINT(token)
        except ValueError:
            raise exceptions.MpdArgError(f"Invalid window: {value}")

    if ":" not in value:
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

MARKER = "protocol.RANGE()` と同じ `protocol.UINT()`"
if MARKER in s:
    print("window厳密数値パース already patched, skip")
else:
    assert s.count(OLD_FUNC) == 1, f"OLD_FUNC count={s.count(OLD_FUNC)}"
    s = s.replace(OLD_FUNC, NEW_FUNC, 1)
    open(p, "w").write(s)
    print(
        "patched music_db.py: _mpd_parse_window()が全角数字等の非ASCII数値や"
        "UINT32上限超過の巨大数値を黙って受理してしまう不具合を修正 "
        "(protocol.UINT()へ委譲しRANGE()と同じ検証を共有)"
    )
