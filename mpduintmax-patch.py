# protocol.UINT() (mopidy_mpd/protocol/__init__.py) に上限チェックが無いため、
# tlid(SONGID)を受け取る `deleteid`/`playlistid`/`moveid`/`swapid`/`prioid`/
# `rangeid`/`addtagid`/`cleartagid` の計8コマンドで、桁数だけ正しい巨大な数字列
# (例: "9999999999") を渡すと実MPDと異なるACKコードが返ってしまう不具合を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実MPD本体 (gh rawで src/protocol/ArgParser.cxx の ParseCommandArgUnsigned() を
# 確認) は `strtoul(s, &endptr, 10)` の後、`value > max_value` (呼び出し側が
# maxを省略した場合は std::numeric_limits<unsigned>::max() == 4294967295) を
# 即座に `ACK_ERROR_ARG` (コード2) `Number too large` として拒否する。この関数は
# src/command/QueueCommands.cxx の handle_deleteid/handle_playlistid/
# handle_moveid/handle_swapid/handle_prioid 等が `args.ParseUnsigned(0)` として
# 共通利用しており、SONGIDが実在するかどうかを見る前段でパースだけで弾かれる。
#
# 一方 mopidy_mpd の UINT() は Python の任意精度 int() をそのまま使うため上限が
# 無く、パースは常に成功し、後段の「そのtlidがキューに存在するか」判定
# (`exceptions.MpdNoExistError("No such song")`, ACK_ERROR_NO_EXIST=50) に
# フォールスルーしてしまう。つまり実MPDならACK 2(引数エラー)になるべき場面で
# mopidy_mpdはACK 50(存在しない)を返してしまい、ACKコード自体が非互換になる。
#
# BACKLOG.md全体を`4294967295`/`UINT32`/`ParseCommandArgUnsigned`/`Number too
# large`等で検索し、直近のmpdstrictnumparse-patch.py(文字集合の緩さ)や
# mpdsetvolrange-patch.py/mpdprioboundary-patch.py(意味論的な範囲/クランプ)は
# いずれも別の側面を扱ったもので、UINT()自体に上限が無い点は未着手であることを
# 確認済み。delete/move/shuffle/prio等のPOSITION(RANGE)系コマンドは既存の
# 境界チェック(mpddeleteboundary-patch.py/mpdprioboundary-patch.py)が
# `start > 実際の長さ` を先に `exceptions.MpdArgError("Bad song index")`
# (ACK 2)として弾くため、たまたま実MPDと同じACKコードになっており影響を
# 受けない。
#
# 修正方針: UINT()の`int(value)`直後に、実MPDのParseCommandArgUnsigned()の
# デフォルト上限(unsigned最大値 0xFFFFFFFF = 4294967295)相当の範囲チェックを
# 追加し、超過時はValueError("Number too large")を送出する。Commands.add()の
# 既存ラッパーがValueErrorをexceptions.MpdArgError(ACK 2)へ変換する流儀
# (mpdstrictnumparse-patch.py等と同じ)により、tlidを扱う8コマンド全てが
# 「存在しないtlid」(ACK 50)ではなく「引数エラー」(ACK 2)を返すようになり
# 実MPDのACKコードと一致する。RANGE()はUINT()を内部で呼ぶ共有実装のため
# 自動的に波及するが、delete/move/shuffle/prioは既存の境界チェックが先に
# 効くため実害の無い変更に留まる。
#
# 実機再現 (dev mopidy 6601): `search any "X"` → `addid "<実URI>"` で
# tlidを1つ用意 → `deleteid "9999999999"` は修正前 `ACK [50@0] {deleteid}
# No such song`、修正後 `ACK [2@0] {deleteid} Number too large`。
# `playlistid`/`moveid`/`swapid`/`prioid`/`rangeid`/`addtagid`/`cleartagid`も
# 同様。実在するtlidに対する各コマンドの正常応答は無変更。

p = "mopidy_mpd/protocol/__init__.py"
s = open(p).read()

MARKER = "_MPD_UINT_MAX"
if MARKER in s:
    print("UINT() upper bound guard already patched, skip")
else:
    OLD_UINT = (
        "def UINT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches \d+ into an integer."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid integer")\n'
        "    if not _MPD_STRICT_UINT_RE.match(value):\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    return int(value)\n"
    )
    assert s.count(OLD_UINT) == 1, f"OLD_UINT count={s.count(OLD_UINT)}"
    NEW_UINT = (
        "_MPD_UINT_MAX = 0xFFFFFFFF\n\n\n"
        "def UINT(value):  # noqa: N802\n"
        r'    r"""Converts a value that matches \d+ into an integer."""'
        "\n"
        "    if value is None:\n"
        '        raise ValueError("None is not a valid integer")\n'
        "    if not _MPD_STRICT_UINT_RE.match(value):\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    value = int(value)\n"
        "    if value > _MPD_UINT_MAX:\n"
        '        raise ValueError("Number too large")\n'
        "    return value\n"
    )
    s = s.replace(OLD_UINT, NEW_UINT, 1)

    open(p, "w").write(s)
    print(
        "patched protocol/__init__.py: UINT()にunsigned最大値(4294967295)を"
        "超える数値を拒否する上限チェックを追加(tlidを扱うdeleteid等が"
        "実MPDと異なりACK 50 No such songを返していたのをACK 2 Number too "
        "largeへ修正)"
    )
