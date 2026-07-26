# mopidy-mpd 3.3.0 の `clearerror` (mopidy_mpd/protocol/status.py) は
# `raise MpdNotImplemented` のスタブで常に ACK エラーになる。TODO 全項目消化済みのため
# 自走エージェントが mopidy_mpd 残りの MpdNotImplemented スタブ (listfiles/rangeid/
# addtagid/cleartagid/clearerror/listneighbors) を洗い出し、rmpc 本体 (mierak/rmpc) を
# 実際に clone して grep したが、`clearerror` を送信する箇所は皆無 (listneighbors 等と
# 同じく rmpc はこの機能を持たない) と判明。ただしこれは mixrampdb/mixrampdelay
# (mpdmixramp-patch.py)・replay_gain_mode/replay_gain_status (mpdreplaygain-patch.py)・
# decoders (mpddecoders-patch.py) と同種の「rmpc固有ではなく標準 MPD プロトコル準拠の
# 不備」に該当すると判断: 実 MPD (MusicPlayerDaemon/MPD src/command/PlayerCommands.cxx
# handle_clearerror) を gh api で実際にソース確認したところ、引数なしで常に
# `client.GetPlayerControl().LockClearError()` を呼んで無条件に OK を返すだけの
# 副作用薄いコマンドと判明 (mpc・ncmpcpp 等の汎用 MPD クライアントが標準的に使う基本
# コマンドであり、これが常に ACK エラーになる現状は crossfade/mixrampdb 同様のギャップ)。
#
# 実装方針: mopidy core (mopidy/core/playback.py) 自体は「最後の再生エラーメッセージ」を
# 保持・通知する仕組みを一切持たない (CoreListener に track_playback_error 相当のイベントが
# 存在しないことを mopidy/core/listener.py で確認済み) ため、mopidy_mpd の `status` は
# 元々 `error` フィールドを一度も出力しない (エラー無し=フィールド省略、は実 MPD 仕様上も
# 正当)。つまり「クリアすべきエラー状態」がそもそも常に空であり、`clearerror` は
# 実 MPD の「エラーが無ければ何もせず OK」ケースと常に一致する。よって crossfade/mixrampdb
# のような揮発性ストアは不要で、単に無条件 OK (関数末尾に到達し暗黙の None を返す、
# protocol.py 側で OK のみの応答になる既存の noidle 等と同じパターン) に差し替えるだけで
# 実 MPD 仕様と完全に一致する。

pp = "mopidy_mpd/protocol/status.py"
s = open(pp).read()

MARKER = "# クリアすべき状態が元から無い"
if MARKER in s:
    print("status.py already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("clearerror")\n'
        "def clearerror(context):\n"
        '    """\n'
        "    *musicpd.org, status section:*\n"
        "\n"
        "        ``clearerror``\n"
        "\n"
        "        Clears the current error message in status (this is also\n"
        "        accomplished by any command that starts playback).\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '@protocol.commands.add("clearerror")\n'
        "def clearerror(context):\n"
        '    """\n'
        "    *musicpd.org, status section:*\n"
        "\n"
        "        ``clearerror``\n"
        "\n"
        "        Clears the current error message in status (this is also\n"
        "        accomplished by any command that starts playback).\n"
        '    """\n'
        "    # mopidy core は再生エラーの状態を一切保持しないため (status の `error`\n"
        "    # フィールドは常に省略、CoreListener に相当イベントも存在しない)、\n"
        "    # クリアすべき状態が元から無い = 常に無条件 OK が実 MPD 仕様と一致する。\n"
        "    pass\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(pp, "w").write(s)
    print("patched status.py: clearerror を無条件 OK に実装")
