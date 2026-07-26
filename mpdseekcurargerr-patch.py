# `seekcur {TIME}` (相対 `+`/`-` 修飾込み) に非数値の TIME (`seekcur "abc"` 等) を
# 渡すと `mopidy_mpd/protocol/playback.py` の `seekcur()` 内で手動パースしている
# `protocol.FLOAT(time)`/`protocol.UFLOAT(time)` が素の `ValueError` を送出し、
# 捕捉されずに MPD セッションが切断されてしまう不具合 (サーバ本体は生存、
# 当該コネクションのみ切断)。
#
# 他の類似コマンド (`seek`/`seekid` は `@protocol.commands.add(..., seconds=
# protocol.UFLOAT)` のようにデコレータの引数バリデータとして宣言しているため、
# フレームワーク側の `Commands.add.<locals>.validate()`
# (`mopidy_mpd/protocol/__init__.py`) が `except ValueError: raise
# exceptions.MpdArgError("incorrect arguments")` で捕捉し `ACK incorrect
# arguments` に変換する) と違い、`seekcur` は `time` の型宣言が無く関数本体で
# 手動パースしているためこの保護を受けられない。
# mpdseekcurstop-patch.py (`seekcur` の停止中ガード) の実機検証中に副産物として
# 発見 (自走エージェントによる新規発見)。
#
# 修正: `time` のパース (`+`/`-` 相対なら `protocol.FLOAT`、絶対なら
# `protocol.UFLOAT`) を関数冒頭に一本化して try/except で囲み、`ValueError` を
# `seek`/`seekid` と同じ `exceptions.MpdArgError("incorrect arguments")` に変換
# する。停止中ガード (`_MpdSeekCurPlayerSyncError`, mpdseekcurstop-patch.py) は
# 実 MPD の「引数検証がハンドラ本体より先に走る」慣行 (デコレータ宣言の
# `seek`/`seekid` はまさにこの順序になる) に合わせ、パースの後・
# `core.playback.seek()` 呼び出しの前に判定する (パース自体は state に依存
# しないため、順序を入れ替えても停止中ガードの効果は変わらない)。

p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

NEW = (
    "def seekcur(context, time):\n"
    '    """\n'
    "    *musicpd.org, playback section:*\n"
    "\n"
    "        ``seekcur {TIME}``\n"
    "\n"
    "        Seeks to the position ``TIME`` within the current song. If prefixed by\n"
    "        '+' or '-', then the time is relative to the current playing position.\n"
    '    """\n'
    '    relative = time.startswith(("+", "-"))\n'
    "    try:\n"
    "        value = protocol.FLOAT(time) if relative else protocol.UFLOAT(time)\n"
    "    except ValueError:\n"
    '        raise exceptions.MpdArgError("incorrect arguments")\n'
    "    if context.core.playback.get_state().get() == PlaybackState.STOPPED:\n"
    '        # 実MPDのSeekCurrentは`!playing`(PLAY/PAUSE状態でない)を無条件で\n'
    "        # NotPlaying扱いする。ここで弾かないとcore.playback.seek()が\n"
    "        # STOPPED時の暗黙play()を誘発し、クライアントが意図しない\n"
    "        # 停止中->再生中への遷移がサイレントに起きてしまう。\n"
    '        raise _MpdSeekCurPlayerSyncError("Not playing")\n'
    "    if relative:\n"
    "        position = context.core.playback.get_time_position().get()\n"
    "        position += int(value * 1000)\n"
    "        context.core.playback.seek(position).get()\n"
    "    else:\n"
    "        position = int(value * 1000)\n"
    "        context.core.playback.seek(position).get()\n"
)

if NEW in s:
    print("seekcur() arg-error guard already patched, skip")
else:
    OLD = (
        "def seekcur(context, time):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``seekcur {TIME}``\n"
        "\n"
        "        Seeks to the position ``TIME`` within the current song. If prefixed by\n"
        "        '+' or '-', then the time is relative to the current playing position.\n"
        '    """\n'
        "    if context.core.playback.get_state().get() == PlaybackState.STOPPED:\n"
        '        # 実MPDのSeekCurrentは`!playing`(PLAY/PAUSE状態でない)を無条件で\n'
        "        # NotPlaying扱いする。ここで弾かないとcore.playback.seek()が\n"
        "        # STOPPED時の暗黙play()を誘発し、クライアントが意図しない\n"
        "        # 停止中->再生中への遷移がサイレントに起きてしまう。\n"
        '        raise _MpdSeekCurPlayerSyncError("Not playing")\n'
        "    if time.startswith((\"+\", \"-\")):\n"
        "        position = context.core.playback.get_time_position().get()\n"
        "        position += int(protocol.FLOAT(time) * 1000)\n"
        "        context.core.playback.seek(position).get()\n"
        "    else:\n"
        "        position = int(protocol.UFLOAT(time) * 1000)\n"
        "        context.core.playback.seek(position).get()\n"
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: seekcurの非数値TIMEが素のValueErrorで"
        "MPDセッションを切断してしまう不具合を修正 (ACK incorrect argumentsへ)"
    )
