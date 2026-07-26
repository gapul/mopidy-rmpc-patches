# find/search/count/playlistfind/playlistsearchが共有するフィルタ式パーサの
# `(prio >= "VALUE")`疑似タグ用ヘルパ `_mpd_parse_prio_filter_value()`
# (music_db.py、mpdpriofilter-patch.py導入) が、数値部分の妥当性チェックに
# Pythonの生の`re.fullmatch(r"\d+", raw_value)`+素の`int()`を使っており、
# 全角数字等の非ASCII"digit"文字を黙って受理してしまう不具合を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# Python正規表現の`\d`はデフォルトでUnicode対応のため
# `re.fullmatch(r"\d+", "５０")`はTrue、`int("５０")`は50になる
# (実測で確認済み)。既に`mpdstrictnumparse-patch.py`/`mpduintmax-patch.py`/
# `mpdwindowstrict-patch.py`/`mpdpositionstrict-patch.py`/
# `mpdsearchaddplposstrict-patch.py`で繰り返し修正されてきた「str.isdigit()/
# 生の\dはUnicode桁を誤って受理する」バグと同じクラスだが、prioフィルタの
# VALUEパーサだけは横展開が漏れていた。
#
# 実MPD本体(gh rawでsrc/song/Filter.cxx ParseExpression()の
# LOCATE_TAG_PRIORITY分岐を確認)は`strtoul(s, &endptr, 10)`を使い、
# `endptr == s`(1文字も数字として消費できない)ならACK Number expectedを
# 返す。strtoulはCロケールのASCII '0'-'9'のみを走査するため全角数字は
# 1文字も消費できずエラーになる。兄弟パーサ`protocol.UINT()`は既に
# `_MPD_STRICT_UINT_RE`(mpdstrictnumparse-patch.py)へこの検証を統合済みで、
# 本パッチはこれに委譲する。
#
# BACKLOG.md全体を`_mpd_parse_prio_filter_value`で検索し、既出は
# mpdpriofilter-patch.py本体(prioフィルタ機能自体の新規実装)のみで、
# VALUEの数値検証の緩さを扱った項目が無いことを確認済み。
#
# 修正: `_mpd_parse_prio_filter_value()`の`re.fullmatch(r"\d+", raw_value)`+
# `int(raw_value)`を`protocol.UINT(raw_value)`呼び出し(ValueError捕捉->
# 既存の`MpdArgError("Number expected")`へ変換)へ置換。0-255範囲チェックは
# 無変更。
#
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント): `searchadd`で実トラックを
# キューに追加し`prioid "50" "1"`でId=1にPrio: 50を設定。
# `playlistfind "(prio >= \"５０\")"`(全角50)が修正前OK(Id=1が誤ってヒット、
# int("５０")==50として解釈)、修正後`ACK [2@0] {playlistfind} Number
# expected`に変化することを確認。回帰確認: 半角`"50"`は修正前後とも
# Id=1がヒットし変化なし、範囲外の半角`"999"`は修正前後ともACK Invalid
# priority valueで変化なし、不正演算子`prio > "50"`は修正前後とも
# ACK '>=' expectedで変化なし。mopidy.logに新規ERROR/Traceback 0件。

MUSIC_DB = "mopidy_mpd/protocol/music_db.py"

MARKER = "mpdpriofiltervaluestrict-patch"

s = open(MUSIC_DB).read()
if MARKER in s:
    print("prio filter value strict numeric parsing already present, skip")
else:
    OLD_FUNC = (
        "def _mpd_parse_prio_filter_value(op, raw_value):\n"
        '    """`(prio OP "VALUE")` の OP/VALUE をパースする。実MPD (Filter.cxx\n'
        "    LOCATE_TAG_PRIORITY) は演算子 `>=` のみを受け付け (ソース中のTODOで他\n"
        "    演算子は実MPD自身も未対応と明記)、VALUE は 0-255 の整数のみ\n"
        '    (`uint8_t`、超えると `Invalid priority value` でACK)。"""\n'
        '    if op != ">=":\n'
        "        raise exceptions.MpdArgError(\"'>=' expected\")\n"
        '    if not re.fullmatch(r"\\d+", raw_value):\n'
        '        raise exceptions.MpdArgError("Number expected")\n'
        "    value = int(raw_value)\n"
        "    if value > 255:\n"
        '        raise exceptions.MpdArgError("Invalid priority value")\n'
        "    return value\n"
    )
    assert s.count(OLD_FUNC) == 1, f"{MUSIC_DB}:_mpd_parse_prio_filter_value old_func count={s.count(OLD_FUNC)}"
    NEW_FUNC = (
        "def _mpd_parse_prio_filter_value(op, raw_value):\n"
        '    """`(prio OP "VALUE")` の OP/VALUE をパースする。実MPD (Filter.cxx\n'
        "    LOCATE_TAG_PRIORITY) は演算子 `>=` のみを受け付け (ソース中のTODOで他\n"
        "    演算子は実MPD自身も未対応と明記)、VALUE は 0-255 の整数のみ\n"
        '    (`uint8_t`、超えると `Invalid priority value` でACK)。"""\n'
        f"    # {MARKER}: 数値部分は protocol.UINT() に委譲し、\n"
        "    # position/window等と同じASCII数字限定チェックを共有する\n"
        "    # (生の re.fullmatch(r\"\\d+\", ...) はUnicode対応のため全角数字等も\n"
        "    # 誤って受理してしまう)。\n"
        '    if op != ">=":\n'
        "        raise exceptions.MpdArgError(\"'>=' expected\")\n"
        "    try:\n"
        "        value = protocol.UINT(raw_value)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("Number expected")\n'
        "    if value > 255:\n"
        '        raise exceptions.MpdArgError("Invalid priority value")\n'
        "    return value\n"
    )
    s = s.replace(OLD_FUNC, NEW_FUNC, 1)
    open(MUSIC_DB, "w").write(s)
    print(
        "patched music_db.py: _mpd_parse_prio_filter_value()が全角数字等の"
        "非ASCII数値を黙って受理してしまう不具合を修正 (protocol.UINT()へ委譲)"
    )
