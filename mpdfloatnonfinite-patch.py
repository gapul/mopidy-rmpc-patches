# `seek {SONGPOS} {TIME}`/`seekid {SONGID} {TIME}`/`seekcur {TIME}` に非有限値
# (`"nan"`/`"inf"`/`"-inf"`、Pythonの`float()`はこれらの文字列を有効な浮動小数点数
# として受理する) を渡すと、実際に再生中の状態でMPDセッションが問答無用で切断されて
# しまう不具合。TODO全項目消化済みのため自走エージェントが、mpdseekcurargerr-patch.py
# (非数値TIMEのValueError切断を修正) 適用後の実機で「では有限だが特殊な浮動小数点値
# (nan/inf) はどうなるか」を追加検証する過程で新規発見。
#
# 根本原因: `mopidy_mpd/protocol/__init__.py` の `protocol.FLOAT`/`protocol.UFLOAT`
# (`seek`/`seekid`はデコレータの引数バリデータとして、`seekcur`は
# mpdseekcurargerr-patch.py適用後に関数冒頭でtry/exceptに包んで手動呼び出し) は
# `float(value)`をそのまま返すだけで nan/inf を弾かない (UFLOATの`if value < 0`も
# nan/infはPythonの比較規則上Falseになるため通過してしまう)。3コマンドとも
# パース成功後、ハンドラ本体で`int(seconds * 1000)`/`int(value * 1000)`を無防備に
# 呼んでおり、`int(float("nan"))`は素の`ValueError`、`int(float("inf"))`/
# `int(float("-inf"))`は素の`OverflowError`を送出する。`seek`/`seekid`の
# デコレータバリデータ(`Commands.add.<locals>.validate()`)は引数変換フェーズの
# `ValueError`しか捕捉せず、この`int()`変換はハンドラ本体の実行時(検証フェーズの
# 外)に起きるため無防備。`seekcur`のmpdseekcurargerr-patch.py由来のtry/exceptも
# `protocol.FLOAT`/`UFLOAT`呼び出し自体しか囲っておらず、その戻り値を使う後段の
# `int()`は対象外。結果、3コマンドいずれも捕捉されない例外がpykka actorの
# `on_receive`まで伝播しMPDセッションが切断される (サーバ本体は生存、当該
# コネクションのみ切断、他の類似の手当て不足パターン=素の例外がACKに変換されず
# セッションを道連れにする、と同系統)。
#
# 実機確認 (dev mopidy 6601、ytmusic実アカウント、YOASOBI 2曲をfindadd+play後):
# 再生中に`seekcur "inf"`→レスポンス無しのままソケットがリセットされ切断
# (mopidy.logに`OverflowError: cannot convert float infinity to integer`、
# `playback.py`, line 426, `position = int(value * 1000)`のTraceback)。新規接続で
# `seekcur "nan"`も同様に切断(`ValueError: cannot convert float NaN to integer`)。
# 別の新規接続で`seek "0" "nan"`(既存のデコレータバリデータ経由の経路)も同様に
# 切断を確認、根本原因が`protocol.UFLOAT`自体の不足でありseekcur固有の問題では
# ないことを実機で裏付けた。
#
# 修正方針: 3箇所を個別に直すのではなく、共有関数`protocol.FLOAT`/`protocol.UFLOAT`
# (mopidy_mpd/protocol/__init__.py) 自体に `math.isfinite()` チェックを追加し
# 非有限値を`ValueError`として弾く。これにより `seek`/`seekid` は既存のデコレータ
# バリデータの`except ValueError`が、`seekcur`は既存のmpdseekcurargerr-patch.pyの
# try/exceptが、いずれも変更無しでそのまま`ACK incorrect arguments`に変換して
# くれる (根本原因を1箇所に閉じ込めることで、将来同じバリデータを使う別コマンドが
# 追加されても同種の切断を再発しない)。

p = "mopidy_mpd/protocol/__init__.py"
s = open(p).read()

NEW_IMPORT = "import inspect\nimport math\n"
NEW_FLOAT = (
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
NEW_UFLOAT = (
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

if NEW_IMPORT in s and NEW_FLOAT in s and NEW_UFLOAT in s:
    print("protocol.FLOAT/UFLOAT non-finite guard already patched, skip")
else:
    OLD_IMPORT = "import inspect\n"
    assert s.count(OLD_IMPORT) == 1, f"OLD_IMPORT count={s.count(OLD_IMPORT)}"
    s = s.replace(OLD_IMPORT, NEW_IMPORT, 1)

    OLD_FLOAT = (
        "def FLOAT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches [+-]\d+(.\d+)? into a float."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid float")\n'
        "    return float(value)\n"
    )
    assert s.count(OLD_FLOAT) == 1, f"OLD_FLOAT count={s.count(OLD_FLOAT)}"
    s = s.replace(OLD_FLOAT, NEW_FLOAT, 1)

    OLD_UFLOAT = (
        "def UFLOAT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches \d+(.\d+)? into a float."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid float")\n'
        "    value = float(value)\n"
        "    if value < 0:\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    return value\n"
    )
    assert s.count(OLD_UFLOAT) == 1, f"OLD_UFLOAT count={s.count(OLD_UFLOAT)}"
    s = s.replace(OLD_UFLOAT, NEW_UFLOAT, 1)

    open(p, "w").write(s)
    print(
        "patched protocol/__init__.py: FLOAT/UFLOATがnan/infを弾かず"
        "seek/seekid/seekcurがint()変換で素のValueError/OverflowErrorを送出し"
        "MPDセッションを切断してしまう不具合を修正 (ACK incorrect argumentsへ)"
    )
