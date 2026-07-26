# `rangeid {ID} {START:END}` (mpdrangeid-patch.py が追加) の独自パーサ
# `_mpd_parse_time_range()` に非有限値の TIME (`rangeid 1 "0:nan"` /
# `rangeid 1 "0:inf"` 等、Python の `float()` はこれらの文字列を有効な浮動小数点数
# として受理する) を渡すと、パース成功後の `round(start * 1000), round(end * 1000)`
# が `round(float("nan"))` で素の `ValueError`、`round(float("inf"))` で素の
# `OverflowError` を送出しMPDセッションが問答無用で切断されてしまう不具合。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが Explore
# サブエージェントに未パッチ・薄くしか監査されていない領域の横断調査を委任し
# 新規発見した項目。
#
# 根本原因: mpdfloatnonfinite-patch.py は `seek`/`seekid`/`seekcur` が共有する
# `protocol.FLOAT`/`protocol.UFLOAT` (mopidy_mpd/protocol/__init__.py) に
# `math.isfinite()` チェックを追加し、この種の nan/inf 由来の未捕捉例外による
# セッション切断を根本修正した。しかし `rangeid` は `songrange` を
# `protocol.commands.add()` のデコレータ引数バリデータとして宣言しておらず
# (mpdrangeid-patch.py 適用後は `songrange=protocol.RANGE` を外し
# `_mpd_parse_time_range()` を関数本体で手動呼び出しする設計)、`protocol.FLOAT`/
# `UFLOAT` を経由しない独自の `float()` 呼び出しであるため、上記修正の対象から
# 完全に漏れていた。かつ `_mpd_parse_time_range()` 内の `try/except ValueError`
# は `float()` の2行のみを囲っており、その外側にある末尾の
# `round(start * 1000), round(end * 1000)` は無防備 (nan は
# `except ValueError` にも掛からず、inf/-inf は `OverflowError` でそもそも
# `ValueError` のサブクラスではないため同様に素通りする)。
# dispatcher.py の `_call_handler_filter`/`_catch_mpd_ack_errors_filter` は
# それぞれ `pykka.ActorDeadError`/`exceptions.MpdAckError` しか捕捉しないため、
# 生の `ValueError`/`OverflowError` が pykka actor の `on_receive` まで伝播し
# `on_failure()` 経由でセッションが切断される
# (mpdseekcurargerr-patch.py/mpdfloatnonfinite-patch.py と同系統、サーバ本体は
# 生存、当該コネクションのみ切断)。
#
# 修正方針: `float()` 変換直後 (try ブロック内) で `math.isfinite()` を検査し、
# 非有限なら他の不正値と同じ `ACK Bad range` へ変換する (mpdfloatnonfinite-patch.py
# が `protocol.FLOAT`/`UFLOAT` に加えたチェックと同じ発想を、共有バリデータを
# 経由しないこの独自パーサにも横展開)。isfinite チェック後の `start`/`end` は
# 常に有限のため、以後の `round()` は安全になる。

cp = "mopidy_mpd/protocol/current_playlist.py"
c = open(cp).read()

MARKER = "nan/inf is not a valid time range value"
if MARKER in c:
    print("current_playlist.py already patched for rangeid non-finite guard, skip")
else:
    OLD_IMPORT = "import re\nimport urllib\n"
    assert c.count(OLD_IMPORT) == 1, f"OLD_IMPORT count={c.count(OLD_IMPORT)}"
    NEW_IMPORT = "import math\nimport re\nimport urllib\n"
    c = c.replace(OLD_IMPORT, NEW_IMPORT, 1)

    OLD_BLOCK = (
        "    try:\n"
        "        start = float(start_str) if start_str.strip() else 0.0\n"
        "        end = float(end_str) if end_str.strip() else 0.0\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("Bad range")\n'
    )
    assert c.count(OLD_BLOCK) == 1, f"OLD_BLOCK count={c.count(OLD_BLOCK)}"
    NEW_BLOCK = (
        "    try:\n"
        "        start = float(start_str) if start_str.strip() else 0.0\n"
        "        end = float(end_str) if end_str.strip() else 0.0\n"
        "        if not (math.isfinite(start) and math.isfinite(end)):\n"
        '            raise ValueError("nan/inf is not a valid time range value")\n'
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("Bad range")\n'
    )
    c = c.replace(OLD_BLOCK, NEW_BLOCK, 1)

    open(cp, "w").write(c)
    print(
        "patched current_playlist.py: rangeidのTIMEにnan/infを渡すと"
        "round()が素のValueError/OverflowErrorを送出しMPDセッションを切断して"
        "しまう不具合を修正 (ACK Bad rangeへ)"
    )
