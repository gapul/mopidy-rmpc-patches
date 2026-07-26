# mpdstickernames-patch.py が追加した `sticker inc`/`sticker dec`
# (_mpd_sticker_inc_dec()) は VALUE の手動パースを `int(value)` で行っており、Python の
# int は任意精度のため極端に桁数の多い文字列 (例: "99999999999999999999999999999999")
# でも ValueError にならず成功する。しかしその後 sqlite3 へバインドパラメータとして
# 渡す際、SQLite の INTEGER は 64bit 範囲までしか扱えず、範囲外だと sqlite3 モジュールが
# 素の OverflowError ("Python int too large to convert to SQLite INTEGER") を送出する。
# 呼び出し元の sticker()/dispatcher.py/session.py のいずれも ValueError (MpdArgError 以外
# の生例外) を捕捉しないため、この OverflowError は捕捉されずMPDセッションが問答無用で
# 切断されてしまう不具合 (サーバ本体は生存、当該コネクションのみ切断)。
# mpdfloatnonfinite-patch.py/mpdrangeidnonfinite-patch.py が同種の「手動パースの生例外が
# 未捕捉のままセッション切断を招く」パターンを float()/round() 系(seek/seekcur/rangeid)で
# 修正済みだが、それらは対象外 (stickers.py の int(value) 起因の OverflowError には未着手)。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが Explore サブエージェント
# に未パッチ・薄くしか監査されていない領域の横断調査を委任し新規発見した項目。
p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "-(2**63) <= delta < 2**63"
if MARKER in s:
    print("sticker inc/dec overflow guard already present, skip")
else:
    old = (
        "def _mpd_sticker_inc_dec(context, field, uri, name, value, sign):\n"
        "    if not name:\n"
        '        raise exceptions.MpdArgError("empty sticker name")\n'
        "    try:\n"
        "        delta = int(value)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError(f"invalid sticker value: {value}")\n'
        "    conn = _mpd_sticker_conn(context)\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"

    # SQLite の INTEGER 列は 64bit 符号付き整数まで (sqlite3 モジュールはこの sqlite3
    # INTEGER range 外の Python int を bind すると OverflowError を送出する)。
    new = (
        "def _mpd_sticker_inc_dec(context, field, uri, name, value, sign):\n"
        "    if not name:\n"
        '        raise exceptions.MpdArgError("empty sticker name")\n'
        "    try:\n"
        "        delta = int(value)\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError(f"invalid sticker value: {value}")\n'
        "    if not (-(2**63) <= delta < 2**63):\n"
        '        raise exceptions.MpdArgError(f"invalid sticker value: {value}")\n'
        "    conn = _mpd_sticker_conn(context)\n"
    )
    s = s.replace(old, new, 1)

    open(p, "w").write(s)
    print("patched stickers.py: sticker inc/dec の VALUE を sqlite3 INTEGER range 内に制限")
