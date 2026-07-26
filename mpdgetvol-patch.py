# mopidy-mpd 3.3.0 は `setvol`/`volume`(相対)は実装済みだが、実 MPD 0.23+ で追加された
# `getvol` (現在の音量を単独で問い合わせるコマンド、musicpd.org protocol
# "Playback options" 節) 自体が未登録 (protocol.commands に無い = 未知コマンド扱い)。
# rmpc 等が起動時に `getvol` を投げてくると `ACK unknown command` になってしまうため
# 追加する。実 MPD の挙動 (src/command/PlayerCommands.cxx handle_getvol) に合わせ、
# ミキサーがあれば `volume: N` (0-100) を1行返し、ミキサーが無ければ (get_volume()が
# None) 何も返さず OK のみとする (status コマンドの volume: -1 とは異なり、getvol は
# 空応答が仕様)。
p = "mopidy_mpd/protocol/playback.py"
s = open(p).read()

MARKER = '@protocol.commands.add("getvol")'
if MARKER in s:
    print("getvol already added, skip")
else:
    anchor = '@protocol.commands.add("setvol", volume=protocol.INT)\n'
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"

    getvol_block = (
        '@protocol.commands.add("getvol")\n'
        "def getvol(context):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``getvol``\n"
        "\n"
        "        Returns the current volume in ``volume: VOL`` (0-100). If there is\n"
        "        no mixer, an empty response is returned.\n"
        '    """\n'
        "    volume = context.core.mixer.get_volume().get()\n"
        "    if volume is None:\n"
        "        return []\n"
        '    return [("volume", volume)]\n'
        "\n"
        "\n"
    )
    s = s.replace(anchor, getvol_block + anchor, 1)
    open(p, "w").write(s)
    print("patched playback.py: getvol を追加 (volume: N を返却、ミキサー無しなら空)")
