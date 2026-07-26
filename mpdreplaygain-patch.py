# mopidy-mpd 3.3.0 の `replay_gain_mode {MODE}` (mopidy_mpd/protocol/playback.py) は
# `raise MpdNotImplemented` のスタブで常に ACK エラーになり、`replay_gain_status` も
# 常に固定文字列 `"replay_gain_mode: off"` を返すだけで実際には設定を反映しない。
# TODO 全項目消化済みのため自走エージェントが rmpc 本体 (mierak/rmpc) を実際に
# clone して grep したが、rmpc-mpd/src/mpd_client.rs 全体・rmpc/src/ui/ 全体を
# 探しても replay_gain 関連の送信箇所は皆無 (rmpc はこの機能を持たない) と判明。
# ただしこれは mixrampdb/mixrampdelay (mpdmixramp-patch.py)・decoders
# (mpddecoders-patch.py)・outputs の plugin フィールド (mpdoutputplugin-patch.py) と
# 同種の「rmpc固有ではなく標準 MPD プロトコル準拠の不備」に該当すると判断した:
# 実 MPD (MusicPlayerDaemon/MPD src/command/PlayerCommands.cxx
# handle_replay_gain_mode/handle_replay_gain_status, src/ReplayGainMode.cxx) を
# WebFetch で実際にソース確認したところ、`replay_gain_mode`/`replay_gain_status` は
# mpc・ncmpcpp 等の汎用 MPD クライアントが標準的に使う基本コマンドであり、
# mopidy_mpd がこれを常に ACK エラーで拒否する現状は「crossfade/mixrampdb 同様に
# 実際の再生へ効果はなくとも、プロトコル層の往復自体は仕様通りにすべき」ギャップと
# 確認した上で着手した項目。
#
# 実 MPD 仕様 (ReplayGainMode.cxx FromString/ToString を実際に確認): 有効な MODE は
# `off`/`track`/`album`/`auto` の4種のみ、未知の値は `std::invalid_argument`
# ("Unrecognized replay gain mode") で ACK エラーになる。`replay_gain_status` は
# 常に `replay_gain_mode: <現在値>` の1行を返す。`replay_gain_mode` 成功時は
# `partition.EmitIdle(IDLE_OPTIONS)` を実際に呼んでおり (PlayerCommands.cxx で確認)、
# 実 MPD では repeat/random/single/consume 等と同じ `options` idle イベントを発火する
# 仕様と確定した。
#
# 実装: crossfade/mixrampdb (mpdcrossfade-patch.py/mpdmixramp-patch.py) と同じ流儀で
# translator.py にモジュールレベルの揮発性ストア (初期値 "off"、プロセス再起動で
# 消えるのは実 MPD の replay gain 設定も同じなので妥当) を追加。mopidy core
# (mopidy/core/playback.py) 自体は ReplayGain の概念を持たず GStreamer レベルで
# 実際の音量補正が掛かることはないため、crossfade/mixrampdb と同種の「プロトコル層の
# 応答のみを仕様に合わせる」実装とした。加えて mount/update (mpdmount-patch.py/
# mpdupdate-patch.py) と同じ `mopidy.listener.send(session.MpdSession, "options")`
# の機構で idle `options` 通知を実際にブロードキャストし (repeat/single 等の core
# 起因の options 変更と同じ全セッション共有の状態であるべきため)、crossfade/mixrampdb
# よりもさらに実 MPD 仕様に近づけた。

pp = "mopidy_mpd/protocol/playback.py"
s = open(pp).read()

MARKER = "translator.set_replay_gain_mode"
if MARKER in s:
    print("playback.py already patched, skip")
else:
    old_block = (
        '@protocol.commands.add("replay_gain_mode")\n'
        "def replay_gain_mode(context, mode):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``replay_gain_mode {MODE}``\n"
        "\n"
        "        Sets the replay gain mode. One of ``off``, ``track``, ``album``.\n"
        "\n"
        "        Changing the mode during playback may take several seconds, because\n"
        "        the new settings does not affect the buffered data.\n"
        "\n"
        "        This command triggers the options idle event.\n"
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
        "\n"
        "\n"
        '@protocol.commands.add("replay_gain_status")\n'
        "def replay_gain_status(context):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``replay_gain_status``\n"
        "\n"
        "        Prints replay gain options. Currently, only the variable\n"
        "        ``replay_gain_mode`` is returned.\n"
        '    """\n'
        '    return "replay_gain_mode: off"  # TODO\n'
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "_MPD_REPLAY_GAIN_MODES = (\"off\", \"track\", \"album\", \"auto\")\n"
        "\n"
        "\n"
        "def _mpdreplaygain_notify():\n"
        "    # session.py への import サイクルを避けるため呼び出し時に遅延import する\n"
        "    # (mpdmount-patch.py の _mpdmount_notify と同じ理由)。\n"
        "    from mopidy import listener\n"
        "    from mopidy_mpd import session as mpd_session\n"
        "\n"
        '    listener.send(mpd_session.MpdSession, "options")\n'
        "\n"
        "\n"
        '@protocol.commands.add("replay_gain_mode")\n'
        "def replay_gain_mode(context, mode):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``replay_gain_mode {MODE}``\n"
        "\n"
        "        Sets the replay gain mode. One of ``off``, ``track``, ``album``.\n"
        "\n"
        "        Changing the mode during playback may take several seconds, because\n"
        "        the new settings does not affect the buffered data.\n"
        "\n"
        "        This command triggers the options idle event.\n"
        '    """\n'
        "    if mode not in _MPD_REPLAY_GAIN_MODES:\n"
        '        raise exceptions.MpdArgError("Unrecognized replay gain mode")\n'
        "    translator.set_replay_gain_mode(mode)\n"
        "    _mpdreplaygain_notify()\n"
        "\n"
        "\n"
        '@protocol.commands.add("replay_gain_status")\n'
        "def replay_gain_status(context):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``replay_gain_status``\n"
        "\n"
        "        Prints replay gain options. Currently, only the variable\n"
        "        ``replay_gain_mode`` is returned.\n"
        '    """\n'
        '    return f"replay_gain_mode: {translator.get_replay_gain_mode()}"\n'
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(pp, "w").write(s)
    print("patched playback.py: replay_gain_mode/replay_gain_status を実装 (揮発性ストア + idle options 通知)")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER2 = "_replay_gain_mode"
if MARKER2 in t:
    print("translator.py already patched, skip")
else:
    anchor = (
        "def next_update_job_id():\n"
        "    global _update_job_id\n"
        "    _update_job_id += 1\n"
        "    return _update_job_id\n"
    )
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "\n"
        "# replay_gain_mode/replay_gain_status (playback.py) 用の揮発性ストア。\n"
        "# 実 MPD の ReplayGainMode も接続毎ではなくプロセス全体で共有される設定であり、\n"
        "# プロセス再起動で消えるのは実 MPD の replay gain 設定も同じなので妥当。\n"
        '_replay_gain_mode = "off"\n'
        "\n"
        "\n"
        "def set_replay_gain_mode(mode):\n"
        "    global _replay_gain_mode\n"
        "    _replay_gain_mode = mode\n"
        "\n"
        "\n"
        "def get_replay_gain_mode():\n"
        "    return _replay_gain_mode\n"
    )
    t = t.replace(anchor, anchor + store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: replay_gain_mode の揮発性ストアを追加")
