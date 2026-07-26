# protocol.UINT/INT/FLOAT/UFLOAT/FLOAT_ALLOW_NAN (mopidy_mpd/protocol/__init__.py)
# の数値引数パーサが、実MPD本体のstrtoul()/strtol()/strtod() (Cロケール、ASCII
# 0-9のみを数字として認識しトレイリングガベージがあれば全体を拒否) よりも遥かに
# 緩く、以下2種の非ASCII/非数値表記を無条件に受理してしまう不具合を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# (1) UINTの`value.isdigit()`はUnicode対応のための全角数字("１２３")や
#     タイ数字("๓")等の非ASCII"digit"文字を通してしまい、後続の`int(value)`も
#     Pythonの数値リテラルパーサがUnicode数字を受理するため変換に成功してしまう
#     (`"１２３".isdigit()` == True、`int("１２３")` == 123)。INT/FLOAT/UFLOAT/
#     FLOAT_ALLOW_NANはisdigit()プレフィルタすら無く直接int()/float()を呼ぶため
#     同じ穴がある。
# (2) INT/FLOAT/UFLOAT/FLOAT_ALLOW_NANは、Python 3.6+の数値リテラル構文である
#     アンダースコア桁区切り("1_0"→10、"1_00.5"→100.5)も無条件に受理してしまう
#     (UINTだけは`"1_0".isdigit()`がFalseのためこの1件に限り偶然通過しない)。
#
# 実MPD本体 (gh rawで src/protocol/ArgParser.cxx の
# ParseCommandArgUnsigned()/ParseCommandArgInt()を確認) は
# `strtoul(s, &endptr, 10)`/`strtol(s, &test, 10)`のendptr/testが文字列の
# 終端(NUL)に達しない場合(=末尾に未消費文字が残る場合)は`endptr == s ||
# *endptr != 0`で無条件に`ACK Integer expected`を返す。strtoul/strtolは
# Cロケールの ASCII '0'-'9' のみを数字として走査するため、全角数字の生の
# UTF-8バイト列や区切りのアンダースコアに遭遇した時点で走査を止め、それ以降が
# 未消費文字として残りエラーになる。mopidy_mpdのトークナイザ
# (mopidy_mpd/tokenize.py PARAM_RE) は`"`/`'`以外の`ord >= 0x20`な文字を
# 無条件にクォート無し引数として通すため、`setvol 1_0`や`setvol １２`
# (生UTF-8バイト)はいずれもクォート回避無しでワイヤ上そのまま送信できる。
#
# BACKLOG.md全体を`isdigit`/`strtoul`/`strtol`/`protocol\.UINT`/`protocol\.INT`/
# `def UINT`/`def INT`で検索し、既存のヒットはUINT対RANGE/UINT対FLOATの
# 意味論的な型不一致(setvolの範囲外値等、既にmpdsetvolrange-patch.py等で対応済み)
# のみで、パーサ自体の文字集合の緩さを扱った項目が無いことを確認済み。
#
# 修正方針: 各パーサの数値変換(int()/float())の直前に、strtol/strtod相当の
# ASCII限定書式(符号+ASCII数字のみ、アンダースコア無し)を要求する正規表現の
# 事前検証を追加する。FLOAT系は実strtodが"inf"/"infinity"/"nan"
# (大文字小文字問わず)を正当な入力として消費しきる(パース自体は成功する。
# これらを拒否するのはmpdfloatnonfinite-patch.py/mpdmixrampdelaynan-patch.py
# が追加した後段のmath.isfinite()/isnan()チェックの役目であり、パーサ自体では
# ない)ため、正規表現にもinf/infinity/nanの特殊形を許容する分岐を含める
# (既存のnan/inf拒否ロジックは無変更のまま働き続ける)。
#
# 実機再現 (dev mopidy 6601、ミキサー有り): `setvol 40` → OK →
# `setvol 1_0` → 修正前はOKでvolumeが10になってしまう(int("1_0")==10、
# 実MPDならACK Integer expected)。`setvol 40`で復元後 `setvol １２`
# (全角"12"の生UTF-8バイト) → 修正前はOKでvolumeが12になってしまう
# (実MPDならACK Integer expected)。`setvol 40`で復元。`mixrampdb 1_0.5`
# (FLOAT側、再生状態に影響しない設定コマンドのため即座に安全に検証可能)も
# 同様に修正前はOKで10.5を受理してしまう。

p = "mopidy_mpd/protocol/__init__.py"
s = open(p).read()

MARKER = "_MPD_STRICT_INT_RE"
if MARKER in s:
    print("protocol number-parser strict ASCII guard already patched, skip")
else:
    OLD_IMPORT = "import inspect\nimport math\n\n"
    assert s.count(OLD_IMPORT) == 1, f"OLD_IMPORT count={s.count(OLD_IMPORT)}"
    NEW_IMPORT = (
        "import inspect\nimport math\nimport re\n\n"
        '_MPD_STRICT_INT_RE = re.compile(r"^[+-]?[0-9]+$")\n'
        '_MPD_STRICT_UINT_RE = re.compile(r"^[0-9]+$")\n'
        "_MPD_STRICT_FLOAT_RE = re.compile(\n"
        r'    r"^[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"'
        "\n"
        r'    r"|^[+-]?(?:inf(?:inity)?|nan)$",'
        "\n"
        "    re.IGNORECASE,\n"
        ")\n\n"
    )
    s = s.replace(OLD_IMPORT, NEW_IMPORT, 1)

    OLD_INT = (
        "def INT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches [+-]?\d+ into an integer."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid integer")\n'
        "    # TODO: check for whitespace via value != value.strip()?\n"
        "    return int(value)\n"
    )
    assert s.count(OLD_INT) == 1, f"OLD_INT count={s.count(OLD_INT)}"
    NEW_INT = (
        "def INT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches [+-]?\d+ into an integer."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid integer")\n'
        "    if not _MPD_STRICT_INT_RE.match(value):\n"
        '        raise ValueError("Integer expected")\n'
        "    # TODO: check for whitespace via value != value.strip()?\n"
        "    return int(value)\n"
    )
    s = s.replace(OLD_INT, NEW_INT, 1)

    OLD_UINT = (
        "def UINT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches \d+ into an integer."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid integer")\n'
        "    if not value.isdigit():\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    return int(value)\n"
    )
    assert s.count(OLD_UINT) == 1, f"OLD_UINT count={s.count(OLD_UINT)}"
    NEW_UINT = (
        "def UINT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches \d+ into an integer."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid integer")\n'
        "    if not _MPD_STRICT_UINT_RE.match(value):\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    return int(value)\n"
    )
    s = s.replace(OLD_UINT, NEW_UINT, 1)

    OLD_FLOAT = (
        "def FLOAT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches [+-]\d+(.\d+)? into a float."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid float")\n'
        "    value = float(value)\n"
        "    if not math.isfinite(value):\n"
        '        raise ValueError("nan/inf is not a valid float")\n'
        "    return value\n"
    )
    assert s.count(OLD_FLOAT) == 1, f"OLD_FLOAT count={s.count(OLD_FLOAT)}"
    NEW_FLOAT = (
        "def FLOAT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches [+-]\d+(.\d+)? into a float."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid float")\n'
        "    if not _MPD_STRICT_FLOAT_RE.match(value):\n"
        '        raise ValueError("Float expected")\n'
        "    value = float(value)\n"
        "    if not math.isfinite(value):\n"
        '        raise ValueError("nan/inf is not a valid float")\n'
        "    return value\n"
    )
    s = s.replace(OLD_FLOAT, NEW_FLOAT, 1)

    OLD_UFLOAT = (
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
    assert s.count(OLD_UFLOAT) == 1, f"OLD_UFLOAT count={s.count(OLD_UFLOAT)}"
    NEW_UFLOAT = (
        "def UFLOAT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches \d+(.\d+)? into a float."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid float")\n'
        "    if not _MPD_STRICT_FLOAT_RE.match(value):\n"
        '        raise ValueError("Float expected")\n'
        "    value = float(value)\n"
        "    if not math.isfinite(value):\n"
        '        raise ValueError("nan/inf is not a valid float")\n'
        "    if value < 0:\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    return value\n"
    )
    s = s.replace(OLD_UFLOAT, NEW_UFLOAT, 1)

    OLD_FLOAT_ALLOW_NAN = (
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
    assert (
        s.count(OLD_FLOAT_ALLOW_NAN) == 1
    ), f"OLD_FLOAT_ALLOW_NAN count={s.count(OLD_FLOAT_ALLOW_NAN)}"
    NEW_FLOAT_ALLOW_NAN = (
        "def FLOAT_ALLOW_NAN(value):  # noqa: N802\n"
        '    r"""Like FLOAT, but also accepts "nan" (mixrampdelay uses nan to\n'
        '    disable MixRamp overlapping and fall back to crossfading)."""\n'
        "    if value is None:\n"
        '        raise ValueError("None is not a valid float")\n'
        "    if not _MPD_STRICT_FLOAT_RE.match(value):\n"
        '        raise ValueError("Float expected")\n'
        "    value = float(value)\n"
        "    if math.isnan(value):\n"
        "        return value\n"
        "    if not math.isfinite(value):\n"
        '        raise ValueError("inf is not a valid float")\n'
        "    return value\n"
    )
    s = s.replace(OLD_FLOAT_ALLOW_NAN, NEW_FLOAT_ALLOW_NAN, 1)

    open(p, "w").write(s)
    print(
        "patched protocol/__init__.py: UINT/INT/FLOAT/UFLOAT/FLOAT_ALLOW_NANが"
        "全角数字等の非ASCII digit文字やアンダースコア桁区切り(\"1_0\")を"
        "無条件に受理してしまう不具合を修正 (strtol/strtod相当のASCII限定"
        "書式チェックを追加)"
    )
