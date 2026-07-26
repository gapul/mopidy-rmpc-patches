# `mixrampdelay {SECONDS}` (mpdmixramp-patch.py が実装、decorator は
# `seconds=protocol.FLOAT`) の docstring 自身が明記する通り、MPD仕様では
# `"nan"` は「MixRampを無効化してクロスフェードへフォールバックする」ための
# 正当な特殊値であり、translator.py の初期値も `float("nan")` になっている。
#
# ところが後発の mpdfloatnonfinite-patch.py (seek/seekid/seekcurがnan/infで
# 素のValueError/OverflowErrorを送出しMPDセッションを切断する不具合対策) が
# 共有バリデータ `protocol.FLOAT`/`UFLOAT` 自体に `math.isfinite()` チェックを
# 追加した際、同じ `protocol.FLOAT` を使う `mixrampdelay` の引数バリデータも
# 無差別に巻き込まれてしまった。結果、クライアントが仕様通り
# `mixrampdelay "nan"` を送ると (パース段階で `ValueError` → デコレータの既存
# except で) `ACK [2@0] {mixrampdelay} incorrect arguments` が返るようになり、
# 一度でも `mixrampdelay 5` のような数値を設定したセッションは、プロトコル
# 経由で二度と "nan" (無効化状態) へ戻せなくなる回帰。
#
# 修正方針: mixrampdelay 専用の緩和版バリデータを新設し、nan のみ明示的に
# 許容する (inf/-inf は実MPDの仕様上も意味を持たない値であり、
# mpdfloatnonfinite-patch.py の意図通り引き続き弾く)。seek/seekid/seekcur が
# 依存する protocol.FLOAT/UFLOAT 自体は変更しない (他のnan/inf切断修正への
# 副作用を避けるため、mixrampdelay だけ個別のバリデータへ分離する)。

p = "mopidy_mpd/protocol/__init__.py"
s = open(p).read()

MARKER = "def FLOAT_ALLOW_NAN"
if MARKER in s:
    print("protocol.FLOAT_ALLOW_NAN already patched, skip")
else:
    anchor = (
        "def UFLOAT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches \d+(.\d+)? into a float."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid float")\n'
        "    value = float(value)\n"
        "    if not math.isfinite(value):\n"
        '        raise ValueError("nan/inf is not a valid float")\n'
        "    if value < 0:\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    return value\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"

    addition = (
        "\n\n"
        "def FLOAT_ALLOW_NAN(value):  # noqa: N802\n"
        '    r"""Like FLOAT, but also accepts "nan" (mixrampdelay uses nan to\n'
        '    disable MixRamp overlapping and fall back to crossfading)."""\n'
        "    if value is None:\n"
        '        raise ValueError("None is not a valid float")\n'
        "    value = float(value)\n"
        "    if math.isnan(value):\n"
        "        return value\n"
        "    if not math.isfinite(value):\n"
        '        raise ValueError("inf is not a valid float")\n'
        "    return value\n"
    )
    s = s.replace(anchor, anchor + addition, 1)
    open(p, "w").write(s)
    print("patched protocol/__init__.py: FLOAT_ALLOW_NAN を追加")

pp = "mopidy_mpd/protocol/playback.py"
sp = open(pp).read()

MARKER2 = 'mixrampdelay", seconds=protocol.FLOAT_ALLOW_NAN'
if MARKER2 in sp:
    print("playback.py mixrampdelay already patched, skip")
else:
    old = '@protocol.commands.add("mixrampdelay", seconds=protocol.FLOAT)\n'
    assert sp.count(old) == 1, f"old count={sp.count(old)}"
    new = '@protocol.commands.add("mixrampdelay", seconds=protocol.FLOAT_ALLOW_NAN)\n'
    sp = sp.replace(old, new, 1)
    open(pp, "w").write(sp)
    print(
        "patched playback.py: mixrampdelayの引数バリデータをFLOAT_ALLOW_NANへ変更し"
        '"nan"(MixRamp無効化)を再び受理するよう修正'
    )
