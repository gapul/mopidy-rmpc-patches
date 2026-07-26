# `sticker inc`/`sticker dec` の _mpd_sticker_inc_dec() は VALUE を Python の厳密な
# `int(value)` (mpdstickernames-patch.py) + 64bit範囲チェック (mpdstickerincoverflow-patch.py)
# で事前検証し、非数値/オーバーフローなら ACK "invalid sticker value" を返すが、実MPD本体
# (MusicPlayerDaemon/MPD、gh rawで src/command/StickerCommands.cxx handle_sticker()/
# DomainHandler::Inc()/Dec() および src/sticker/Database.cxx StickerDatabase::IncValue()/
# DecValue() を確認) は VALUE に対して一切の数値検証を行わない。実装は
# `args[4]`(生の文字列)をそのまま `IncValue(type, uri, name, value)` へ渡し、
# `BindAll(s, type, uri, name, value, value)` で同じ生文字列を
# "INSERT INTO sticker (type, uri, name, value) VALUES (?, ?, ?, ?) ON CONFLICT(type, uri,
# name) DO UPDATE set value = value + ?" の2箇所(新規行のvalue列、および加算オペランド)へ
# バインドするのみで、数値変換はSQLite自身の算術時の暗黙型変換(TEXT値への数値親和性
# 変換、CAST(TEXT AS INTEGER)と同じ前置数値プレフィックス規則)に委ねている。つまり
# 実MPDは非数値/巨大なVALUEを一切拒否せず常にOKを返し、新規作成時は生の文字列を
# そのまま保存する(既存スティッカーへのinc/decのみSQLiteの数値親和性変換で計算される)。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。BACKLOG.md全体を
# `invalid sticker value`/`IncValue`/`DecValue`/`_mpd_sticker_inc_dec`で検索したが、
# mpdstickernames-patch.py(ACK仕様を実MPD未確認のまま新規実装)と
# mpdstickerincoverflow-patch.py(Pythonのint()起因のOverflowError未捕捉クラッシュを
# ACKへ変換しただけ)のみがヒットし、どちらもVALUEをそもそもACKすべきでない
# (real MPDは検証しない)という点は検討されていなかった。修正: 既に実MPDのSQLite
# CAST(value AS INT)相当のセマンティクスへ合わせ込み済みの`_mpd_sticker_as_int()`
# (mpdstickerintcast-patch.py、前置数値プレフィックス抽出+64bit範囲クランプ)を再利用し、
# int(value)の厳密パース+ACKを削除。INSERT時のvalue列バインドも`str(delta)`(Pythonが
# 解釈した数値の文字列化)ではなく生の`value`(クライアントが送った文字列そのもの)に変更し、
# 新規作成時に生文字列を保存する実MPDの挙動を再現する。
import ast

p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "delta = _mpd_sticker_as_int(value)"
if MARKER in s:
    print("sticker inc/dec raw-value/no-validation fix already present, skip")
else:
    old = (
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
        "    try:\n"
        "        conn.execute(\n"
        '            "INSERT INTO sticker (type, uri, name, value) VALUES (?, ?, ?, ?) "\n'
        '            f"ON CONFLICT(type, uri, name) DO UPDATE SET "\n'
        '            f"value = CAST(value AS INTEGER) {sign} ?",\n'
        "            (field, uri, name, str(delta), delta),\n"
        "        )\n"
        "        conn.commit()\n"
        "    finally:\n"
        "        conn.close()\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"

    new = (
        "def _mpd_sticker_inc_dec(context, field, uri, name, value, sign):\n"
        "    if not name:\n"
        '        raise exceptions.MpdArgError("empty sticker name")\n'
        "    delta = _mpd_sticker_as_int(value)\n"
        "    conn = _mpd_sticker_conn(context)\n"
        "    try:\n"
        "        conn.execute(\n"
        '            "INSERT INTO sticker (type, uri, name, value) VALUES (?, ?, ?, ?) "\n'
        '            f"ON CONFLICT(type, uri, name) DO UPDATE SET "\n'
        '            f"value = CAST(value AS INTEGER) {sign} ?",\n'
        "            (field, uri, name, value, delta),\n"
        "        )\n"
        "        conn.commit()\n"
        "    finally:\n"
        "        conn.close()\n"
    )
    s = s.replace(old, new, 1)

    open(p, "w").write(s)
    ast.parse(s)
    print(
        "patched stickers.py: sticker inc/decのVALUE事前検証(ACK)を撤廃し"
        "_mpd_sticker_as_intへ委譲、新規作成時は生のVALUE文字列をそのまま保存するよう変更"
        "(実MPDのIncValue()/DecValue()が数値検証を一切行わない挙動に整合)"
    )
