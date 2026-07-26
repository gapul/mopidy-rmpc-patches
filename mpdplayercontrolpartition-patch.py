# crossfade/mixrampdb/mixrampdelay (mpdcrossfade-patch.py/mpdmixramp-patch.py) と
# replay_gain_mode (mpdreplaygain-patch.py) が、mopidy_mpd/translator.py 上で単なる
# モジュールレベルのグローバル変数 (プロセス全体で1つ) として実装されており、
# newpartition (mpdpartition-patch.py) で作られる複数パーティション間で値が漏れて
# しまう不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て) 新規発見。
#
# 実MPD本体 (gh raw で確認):
#   - src/command/PlayerCommands.cxx handle_crossfade/handle_mixrampdb/
#     handle_mixrampdelay はいずれも `client.GetPlayerControl().SetXxx(...)` を呼び、
#     src/Partition.hxx (`PlayerControl pc;`) の通りPlayerControlはパーティション毎に
#     独立したインスタンスを持つ。
#   - src/command/PlayerCommands.cxx handle_replay_gain_mode は
#     `partition.SetReplayGainMode(new_mode)` を呼び、src/Partition.hxx
#     (`ReplayGainMode replay_gain_mode = ReplayGainMode::OFF;`) の通り
#     replay_gain_mode 自体がPartitionインスタンスのメンバ変数であり、
#     SetReplayGainMode() は自パーティションのみを書き換える
#     (mpdreplaygain-patch.py導入時の既存コメント「実MPDのReplayGainModeも
#     プロセス全体で共有される」は実MPDソース未確認のまま書かれた誤りだった)。
#
# 4値ともパーティション毎に独立するべきところ、translator.pyの実装は
# _crossfade_seconds/_mixrampdb/_mixrampdelay/_replay_gain_mode という単一スカラーを
# 全パーティション(全クライアント接続)で共有しているため、あるパーティションで
# 設定した値が他の無関係なパーティションの status/replay_gain_status にそのまま
# 反映されてしまう。
#
# 実機確認 (TCP 6601、mopidy-ytmusic実アカウント、2接続 A(default)/B(newpartition
# 後にpartition切替)):
#   A: crossfade 15 -> OK
#   B: status -> 修正前は partition: zoneX なのに xfade: 15 が漏れて表示 (期待値は
#      未出力=0)
#   A: mixrampdb -10.5 -> OK
#   B: status -> 修正前は mixrampdb: -10.5 が漏れて表示 (期待値は 0.0)
#   A: replay_gain_mode track -> OK
#   B: replay_gain_status -> 修正前は replay_gain_mode: track が漏れて表示
#      (期待値は off)
#
# BACKLOG.md全体を crossfade/mixramp/replay_gain/パーティション の組み合わせで検索
# したが、mpdvolumepartition-patch.py/mpdoutputpartition-patch.py/
# mpdidlemixerpartition-patch.pyはmixer(音量)/output(出力)のパーティション所有権の
# みを扱っており、crossfade/mixramp/replay_gain_modeの値そのものがパーティション毎に
# 独立していない件は未対応・未blockedと確認。
#
# 修正: mpdpartition-patch.pyの_session_partition/_output_partitionと同じ
# 「パーティション名をキーとする辞書」方式に4値を変更し、set_/get_の各関数へ
# partition引数 (既定値"default"、未指定呼び出し元の後方互換のため) を追加。
# playback.py側の各ハンドラは translator.partition_get(id(context.session))
# (mpdvolumepartition-patch.pyのcontext.session使用パターンと同じ) で自セッションの
# 所属パーティション名を取得しset_/get_へ渡す。delpartition (mpdpartitiondeltoctou-
# patch.pyのpartition_try_delete()) で不要になったパーティションのエントリを
# 各辞書から削除しメモリリークを防ぐ。
#
# 既知の残課題 (スコープ外、mpdidlemixerpartition-patch.pyの前例と同じ分割):
# crossfade/mixrampdb/mixrampdelay/replay_gain_modeの変更が発火するidle "options"
# 通知 (mpdcrossfadeidle-patch.py/mpdreplaygain-patch.pyの_mpdcrossfadeidle_notify/
# _mpdreplaygain_notify) は本パッチでは無条件に全パーティションへbroadcastされる
# ままで未対応。ただしrepeat/random/single/consumeはmopidy coreの単一tracklistを
# 全パーティションが共有するため元々どのパーティションからも見えるべき値であり、
# 同じ"options"通知に相乗りしているcrossfade/mixramp/replay_gain_modeの変更だけを
# 選択的にパーティション限定配送するには、mpdidlemixerpartition-patch.pyと同種の
# 個別配送機構(_session_actor_refs経由のProxyCall直接tell())が別途必要。値自体の
# 漏洩(本パッチが修正するstatus/replay_gain_statusの実害)とは別軸の问题であり、
# 将来セッションの独立項目として残す。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER = "_crossfade_seconds = {}"
if MARKER in t:
    print("translator.py already patched, skip")
else:
    old_store = (
        "# crossfade (playback.py) 用の揮発性ストア。プロセス再起動で消えるのは\n"
        "# 実 MPD の crossfade 設定も同じなので妥当。\n"
        "_crossfade_seconds = 0\n"
        "\n"
        "\n"
        "def set_crossfade(seconds):\n"
        "    global _crossfade_seconds\n"
        "    _crossfade_seconds = seconds\n"
        "\n"
        "\n"
        "def get_crossfade():\n"
        "    return _crossfade_seconds\n"
        "\n"
        "\n"
        "# mixrampdb/mixrampdelay (playback.py) 用の揮発性ストア。crossfade と同種の\n"
        "# 理由でプロセス再起動で消えるのは実MPDの設定も同じなので妥当。mixrampdelay の\n"
        "# 初期値 nan は実MPDのデフォルト(MixRamp無効・クロスフェードへフォールバック)と揃える。\n"
        "_mixrampdb = 0.0\n"
        "_mixrampdelay = float(\"nan\")\n"
        "\n"
        "\n"
        "def set_mixrampdb(decibels):\n"
        "    global _mixrampdb\n"
        "    _mixrampdb = decibels\n"
        "\n"
        "\n"
        "def get_mixrampdb():\n"
        "    return _mixrampdb\n"
        "\n"
        "\n"
        "def set_mixrampdelay(seconds):\n"
        "    global _mixrampdelay\n"
        "    _mixrampdelay = seconds\n"
        "\n"
        "\n"
        "def get_mixrampdelay():\n"
        "    return _mixrampdelay\n"
    )
    assert t.count(old_store) == 1, f"old_store count={t.count(old_store)}"
    new_store = (
        "# crossfade (playback.py) 用の揮発性ストア。実MPD (src/command/\n"
        "# PlayerCommands.cxx handle_crossfade、client.GetPlayerControl()) は\n"
        "# パーティション毎に独立したPlayerControlが保持するため、パーティション名を\n"
        "# キーとする辞書で保持する (mpdplayercontrolpartition-patch.py、未登録\n"
        "# パーティションは実MPD既定値の0扱い)。プロセス再起動で消えるのは実MPDの\n"
        "# 設定も同じなので妥当。\n"
        "_crossfade_seconds = {}\n"
        "\n"
        "\n"
        "def set_crossfade(seconds, partition=\"default\"):\n"
        "    _crossfade_seconds[partition] = seconds\n"
        "\n"
        "\n"
        "def get_crossfade(partition=\"default\"):\n"
        "    return _crossfade_seconds.get(partition, 0)\n"
        "\n"
        "\n"
        "# mixrampdb/mixrampdelay (playback.py) 用の揮発性ストア。crossfade と同じ理由\n"
        "# (実MPDはPlayerControl毎) でパーティション名をキーとする辞書に変更\n"
        "# (mpdplayercontrolpartition-patch.py)。mixrampdelay の未登録時デフォルト nan は\n"
        "# 実MPDのデフォルト(MixRamp無効・クロスフェードへフォールバック)と揃える。\n"
        "_mixrampdb = {}\n"
        "_mixrampdelay = {}\n"
        "\n"
        "\n"
        "def set_mixrampdb(decibels, partition=\"default\"):\n"
        "    _mixrampdb[partition] = decibels\n"
        "\n"
        "\n"
        "def get_mixrampdb(partition=\"default\"):\n"
        "    return _mixrampdb.get(partition, 0.0)\n"
        "\n"
        "\n"
        "def set_mixrampdelay(seconds, partition=\"default\"):\n"
        "    _mixrampdelay[partition] = seconds\n"
        "\n"
        "\n"
        "def get_mixrampdelay(partition=\"default\"):\n"
        "    return _mixrampdelay.get(partition, float(\"nan\"))\n"
    )
    assert new_store != old_store
    t = t.replace(old_store, new_store, 1)

    old_replaygain = (
        "# replay_gain_mode/replay_gain_status (playback.py) 用の揮発性ストア。\n"
        "# 実 MPD の ReplayGainMode も接続毎ではなくプロセス全体で共有される設定であり、\n"
        "# プロセス再起動で消えるのは実 MPD の replay gain 設定も同じなので妥当。\n"
        "_replay_gain_mode = \"off\"\n"
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
    assert t.count(old_replaygain) == 1, f"old_replaygain count={t.count(old_replaygain)}"
    new_replaygain = (
        "# replay_gain_mode/replay_gain_status (playback.py) 用の揮発性ストア。実MPD\n"
        "# (src/Partition.hxx `ReplayGainMode replay_gain_mode`) はパーティション毎の\n"
        "# Partitionインスタンス自身がこの値を保持しSetReplayGainMode()は自パーティション\n"
        "# のみを書き換えるため、crossfade/mixrampdb/mixrampdelayと同じくパーティション名を\n"
        "# キーとする辞書に変更 (mpdplayercontrolpartition-patch.py。旧コメントの「プロセス\n"
        "# 全体で共有される」は実MPDソース未確認のまま書かれた誤りだった)。プロセス再起動で\n"
        "# 消えるのは実MPDのreplay gain設定も同じなので妥当。\n"
        "_replay_gain_mode = {}\n"
        "\n"
        "\n"
        "def set_replay_gain_mode(mode, partition=\"default\"):\n"
        "    _replay_gain_mode[partition] = mode\n"
        "\n"
        "\n"
        "def get_replay_gain_mode(partition=\"default\"):\n"
        "    return _replay_gain_mode.get(partition, \"off\")\n"
    )
    assert new_replaygain != old_replaygain
    t = t.replace(old_replaygain, new_replaygain, 1)

    old_try_delete_tail = "        _partitions.remove(name)\n        return None\n"
    assert t.count(old_try_delete_tail) == 1, f"old_try_delete_tail count={t.count(old_try_delete_tail)}"
    new_try_delete_tail = (
        "        _partitions.remove(name)\n"
        "        # crossfade/mixrampdb/mixrampdelay/replay_gain_modeの当該パーティション分の\n"
        "        # エントリも削除し、再作成不能な名前のゴミがdict内に無期限に残らないようにする\n"
        "        # (mpdplayercontrolpartition-patch.py)。\n"
        "        _crossfade_seconds.pop(name, None)\n"
        "        _mixrampdb.pop(name, None)\n"
        "        _mixrampdelay.pop(name, None)\n"
        "        _replay_gain_mode.pop(name, None)\n"
        "        return None\n"
    )
    t = t.replace(old_try_delete_tail, new_try_delete_tail, 1)

    open(tp, "w").write(t)
    print("patched translator.py: crossfade/mixrampdb/mixrampdelay/replay_gain_mode をパーティション毎の辞書に変更")

pp = "mopidy_mpd/protocol/playback.py"
p = open(pp).read()

MARKER_PB = "translator.set_crossfade(seconds, partition)"
if MARKER_PB in p:
    print("playback.py already patched, skip")
else:
    old_crossfade = (
        '@protocol.commands.add("crossfade", seconds=protocol.UINT)\n'
        "def crossfade(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``crossfade {SECONDS}``\n"
        "\n"
        "        Sets crossfading between songs.\n"
        '    """\n'
        "    translator.set_crossfade(seconds)\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    assert p.count(old_crossfade) == 1, f"old_crossfade count={p.count(old_crossfade)}"
    new_crossfade = (
        '@protocol.commands.add("crossfade", seconds=protocol.UINT)\n'
        "def crossfade(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``crossfade {SECONDS}``\n"
        "\n"
        "        Sets crossfading between songs.\n"
        '    """\n'
        "    partition = translator.partition_get(id(context.session))\n"
        "    translator.set_crossfade(seconds, partition)\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    p = p.replace(old_crossfade, new_crossfade, 1)

    old_mixrampdb = (
        '@protocol.commands.add("mixrampdb", decibels=protocol.FLOAT)\n'
        "def mixrampdb(context, decibels):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``mixrampdb {deciBels}``\n"
        "\n"
        "    Sets the threshold at which songs will be overlapped. Like crossfading but\n"
        "    doesn't fade the track volume, just overlaps. The songs need to have\n"
        "    MixRamp tags added by an external tool. 0dB is the normalized maximum\n"
        "    volume so use negative values, I prefer -17dB. In the absence of mixramp\n"
        "    tags crossfading will be used. See\n"
        "    https://sourceforge.net/projects/mixramp/\n"
        '    """\n'
        "    translator.set_mixrampdb(decibels)\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    assert p.count(old_mixrampdb) == 1, f"old_mixrampdb count={p.count(old_mixrampdb)}"
    new_mixrampdb = (
        '@protocol.commands.add("mixrampdb", decibels=protocol.FLOAT)\n'
        "def mixrampdb(context, decibels):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``mixrampdb {deciBels}``\n"
        "\n"
        "    Sets the threshold at which songs will be overlapped. Like crossfading but\n"
        "    doesn't fade the track volume, just overlaps. The songs need to have\n"
        "    MixRamp tags added by an external tool. 0dB is the normalized maximum\n"
        "    volume so use negative values, I prefer -17dB. In the absence of mixramp\n"
        "    tags crossfading will be used. See\n"
        "    https://sourceforge.net/projects/mixramp/\n"
        '    """\n'
        "    translator.set_mixrampdb(decibels, translator.partition_get(id(context.session)))\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    p = p.replace(old_mixrampdb, new_mixrampdb, 1)

    old_mixrampdelay = (
        '@protocol.commands.add("mixrampdelay", seconds=protocol.FLOAT_ALLOW_NAN)\n'
        "def mixrampdelay(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``mixrampdelay {SECONDS}``\n"
        "\n"
        "        Additional time subtracted from the overlap calculated by mixrampdb. A\n"
        "        value of \"nan\" disables MixRamp overlapping and falls back to\n"
        "        crossfading.\n"
        '    """\n'
        "    translator.set_mixrampdelay(seconds)\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    assert p.count(old_mixrampdelay) == 1, f"old_mixrampdelay count={p.count(old_mixrampdelay)}"
    new_mixrampdelay = (
        '@protocol.commands.add("mixrampdelay", seconds=protocol.FLOAT_ALLOW_NAN)\n'
        "def mixrampdelay(context, seconds):\n"
        '    """\n'
        "    *musicpd.org, playback section:*\n"
        "\n"
        "        ``mixrampdelay {SECONDS}``\n"
        "\n"
        "        Additional time subtracted from the overlap calculated by mixrampdb. A\n"
        "        value of \"nan\" disables MixRamp overlapping and falls back to\n"
        "        crossfading.\n"
        '    """\n'
        "    translator.set_mixrampdelay(seconds, translator.partition_get(id(context.session)))\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    p = p.replace(old_mixrampdelay, new_mixrampdelay, 1)

    old_replay_gain_mode = (
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
        "        raise exceptions.MpdArgError(\"Unrecognized replay gain mode\")\n"
        "    translator.set_replay_gain_mode(mode)\n"
        "    _mpdreplaygain_notify()\n"
    )
    assert p.count(old_replay_gain_mode) == 1, f"old_replay_gain_mode count={p.count(old_replay_gain_mode)}"
    new_replay_gain_mode = (
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
        "        raise exceptions.MpdArgError(\"Unrecognized replay gain mode\")\n"
        "    translator.set_replay_gain_mode(mode, translator.partition_get(id(context.session)))\n"
        "    _mpdreplaygain_notify()\n"
    )
    p = p.replace(old_replay_gain_mode, new_replay_gain_mode, 1)

    old_replay_gain_status = (
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
        "    return f\"replay_gain_mode: {translator.get_replay_gain_mode()}\"\n"
    )
    assert p.count(old_replay_gain_status) == 1, f"old_replay_gain_status count={p.count(old_replay_gain_status)}"
    new_replay_gain_status = (
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
        "    partition = translator.partition_get(id(context.session))\n"
        "    return f\"replay_gain_mode: {translator.get_replay_gain_mode(partition)}\"\n"
    )
    p = p.replace(old_replay_gain_status, new_replay_gain_status, 1)

    open(pp, "w").write(p)
    print("patched playback.py: crossfade/mixrampdb/mixrampdelay/replay_gain_mode/replay_gain_status を自パーティション値で読み書きするよう変更")

sp = "mopidy_mpd/protocol/status.py"
s = open(sp).read()

MARKER_ST = "_status_xfade(futures, partition)"
if MARKER_ST in s:
    print("status.py already patched, skip")
else:
    old_result_head = (
        "    result = [\n"
        '        ("partition", translator.partition_get(id(context.session))),\n'
        '        ("repeat", _status_repeat(futures)),\n'
        '        ("random", _status_random(futures)),\n'
        '        ("single", _status_single(futures)),\n'
        '        ("consume", _status_consume(futures)),\n'
        '        ("playlist", _status_playlist_version(futures)),\n'
        '        ("playlistlength", _status_playlist_length(futures)),\n'
        '        ("mixrampdb", _status_mixrampdb(futures)),\n'
        '        ("state", _status_state(futures)),\n'
        '        ("lastloadedplaylist", translator.get_last_loaded_playlist()),\n'
        "    ]\n"
        "    volume = _status_volume(futures)\n"
        "    if volume >= 0:\n"
        '        result.append(("volume", volume))\n'
        "    xfade = _status_xfade(futures)\n"
        "    if xfade > 0:\n"
        '        result.append(("xfade", xfade))\n'
        "    mixrampdelay = _status_mixrampdelay(futures)\n"
        "    if mixrampdelay > 0:\n"
        '        result.append(("mixrampdelay", mixrampdelay))\n'
    )
    assert s.count(old_result_head) == 1, f"old_result_head count={s.count(old_result_head)}"
    new_result_head = (
        "    partition = translator.partition_get(id(context.session))\n"
        "    result = [\n"
        '        ("partition", partition),\n'
        '        ("repeat", _status_repeat(futures)),\n'
        '        ("random", _status_random(futures)),\n'
        '        ("single", _status_single(futures)),\n'
        '        ("consume", _status_consume(futures)),\n'
        '        ("playlist", _status_playlist_version(futures)),\n'
        '        ("playlistlength", _status_playlist_length(futures)),\n'
        '        ("mixrampdb", _status_mixrampdb(futures, partition)),\n'
        '        ("state", _status_state(futures)),\n'
        '        ("lastloadedplaylist", translator.get_last_loaded_playlist()),\n'
        "    ]\n"
        "    volume = _status_volume(futures)\n"
        "    if volume >= 0:\n"
        '        result.append(("volume", volume))\n'
        "    xfade = _status_xfade(futures, partition)\n"
        "    if xfade > 0:\n"
        '        result.append(("xfade", xfade))\n'
        "    mixrampdelay = _status_mixrampdelay(futures, partition)\n"
        "    if mixrampdelay > 0:\n"
        '        result.append(("mixrampdelay", mixrampdelay))\n'
    )
    s = s.replace(old_result_head, new_result_head, 1)

    old_helpers = (
        "def _status_xfade(futures):\n"
        "    return translator.get_crossfade()\n"
        "\n"
        "\n"
        "def _status_mixrampdb(futures):\n"
        "    return translator.get_mixrampdb()\n"
    )
    assert s.count(old_helpers) == 1, f"old_helpers count={s.count(old_helpers)}"
    new_helpers = (
        "def _status_xfade(futures, partition):\n"
        "    return translator.get_crossfade(partition)\n"
        "\n"
        "\n"
        "def _status_mixrampdb(futures, partition):\n"
        "    return translator.get_mixrampdb(partition)\n"
    )
    s = s.replace(old_helpers, new_helpers, 1)

    old_mixrampdelay_helper = (
        "def _status_mixrampdelay(futures):\n"
        "    return translator.get_mixrampdelay()\n"
    )
    assert s.count(old_mixrampdelay_helper) == 1, f"old_mixrampdelay_helper count={s.count(old_mixrampdelay_helper)}"
    new_mixrampdelay_helper = (
        "def _status_mixrampdelay(futures, partition):\n"
        "    return translator.get_mixrampdelay(partition)\n"
    )
    s = s.replace(old_mixrampdelay_helper, new_mixrampdelay_helper, 1)

    open(sp, "w").write(s)
    print("patched status.py: xfade/mixrampdb/mixrampdelay を自パーティションの値で出力するよう変更")
