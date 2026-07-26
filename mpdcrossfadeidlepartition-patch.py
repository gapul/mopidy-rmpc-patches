# mpdplayercontrolpartition-patch.py が crossfade/mixrampdb/mixrampdelay/
# replay_gain_mode の値自体をパーティション毎の辞書へ分離したが、それらの変更が
# 発火する idle "options" 通知 (mpdcrossfadeidle-patch.py の
# _mpdcrossfadeidle_notify・mpdreplaygain-patch.py の _mpdreplaygain_notify) は
# 依然 `mopidy.listener.send(MpdSession, "options")` による無条件全パーティション
# broadcast のままで未対応だった不具合。mpdplayercontrolpartition-patch.py 自身が
# コメントで残していた既知の残課題 (「将来セッションの独立項目として残す」) を
# 本セッションで消化。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# その既存コメントを起点に新規着手。
#
# 実MPD本体 (gh raw、src/command/PlayerCommands.cxx handle_crossfade/
# handle_mixrampdb/handle_mixrampdelay/handle_replay_gain_mode) を再確認、いずれも
# `partition.EmitIdle(IDLE_OPTIONS)` を呼び、Partition::EmitIdle は自パーティション
# の idle_monitor のみを操作する (mpdidlemixerpartition-patch.py が mixer/output で
# 既に確認済みの Partition::EmitIdle と同一機構)。一方 repeat/random/single/consume
# (_mpdoneshotidle_notify 等) は mopidy core の単一 tracklist を全パーティションが
# 共有する値のため、そちらは既存の全体 broadcast のままが引き続き正しい
# (mpdplayercontrolpartition-patch.py 自身のコメントの通り)。
#
# 実害: rmpc は起動時に `idle` へ入りっぱなしになる接続を各パーティションで持つ。
# パーティションA(default)のクライアントが crossfade/mixrampdb/mixrampdelay/
# replay_gain_mode を変更すると、無関係なパーティションB(newpartition)で
# `idle options` 待機中のrmpc等が誤って起床する (自身のstatus/replay_gain_statusは
# 無変更のまま)。クラッシュや切断は起きないが実MPD仕様違反かつ無駄な起床。
#
# 修正: mpdidlemixerpartition-patch.pyが確立した「pykka ProxyCallを対象セッションの
# actor_refへ直接tell()する個別配送」機構をそのまま再利用。translator.pyの
# _session_actor_refs/_session_partitionを使い、mixer_output_idle_targets()
# (出力所有パーティション基準) と並ぶ汎用版として、任意のパーティション名を
# 直接指定できるpartition_idle_targets(partition)を追加。playback.pyの
# _mpdcrossfadeidle_notify()/_mpdreplaygain_notify()を、呼び出し元が既に計算済みの
# partition (translator.partition_get(id(context.session))) を受け取り、
# mixer_output_idle_targets()と同じProxyCall直接tell()で当該パーティションの
# セッションだけへ配送するよう変更。呼び出し箇所(crossfade/mixrampdb/mixrampdelay/
# replay_gain_mode)は、インライン計算していたpartitionを変数へ束ねてnotifyへ渡す
# だけの変更で済む。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "def partition_idle_targets"
if MARKER_T in t:
    print("translator.py already patched (mpdcrossfadeidlepartition), skip")
else:
    anchor = (
        "def mixer_output_idle_targets():\n"
        "    # 唯一の仮想出力\"Mute\"の所属パーティションと同じパーティションに\n"
        "    # 属するセッションのactor_refのみを返す (実MPD Partition::EmitIdleの\n"
        "    # パーティションスコープ相当)。\n"
        "    with _partition_lock:\n"
        '        owner = _output_partition.get("Mute")\n'
        "        return [\n"
        "            actor_ref\n"
        "            for session_id, actor_ref in _session_actor_refs.items()\n"
        '            if _session_partition.get(session_id, "default") == owner\n'
        "        ]\n"
    )
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    addition = (
        "\n\n"
        "def partition_idle_targets(partition):\n"
        "    # mixer_output_idle_targets()の汎用版: 出力所有パーティションではなく\n"
        "    # 呼び出し元が指定した任意のパーティション名に属するセッションの\n"
        "    # actor_refのみを返す。crossfade/mixrampdb/mixrampdelay/replay_gain_mode\n"
        "    # (mpdplayercontrolpartition-patch.pyでパーティション毎の値に分離済み)の\n"
        "    # options idle通知をパーティション限定配送するために使う\n"
        "    # (mpdcrossfadeidlepartition-patch.py)。\n"
        "    with _partition_lock:\n"
        "        return [\n"
        "            actor_ref\n"
        "            for session_id, actor_ref in _session_actor_refs.items()\n"
        '            if _session_partition.get(session_id, "default") == partition\n'
        "        ]\n"
    )
    t = t.replace(anchor, anchor + addition, 1)
    open(tp, "w").write(t)
    print(
        "patched translator.py: 任意パーティション名でidle対象セッションを絞り込む"
        "partition_idle_targets()を追加"
    )

pp = "mopidy_mpd/protocol/playback.py"
p = open(pp).read()

MARKER_P = "translator.partition_idle_targets"
if MARKER_P in p:
    print("playback.py already patched (mpdcrossfadeidlepartition), skip")
else:
    old_crossfade_notify = (
        "def _mpdcrossfadeidle_notify():\n"
        "    # session.py への import サイクルを避けるため呼び出し時に遅延import する\n"
        "    # (mpdmount-patch.py の _mpdmount_notify と同じ理由)。\n"
        "    from mopidy import listener\n"
        "    from mopidy_mpd import session as mpd_session\n"
        "\n"
        '    listener.send(mpd_session.MpdSession, "options")\n'
    )
    assert p.count(old_crossfade_notify) == 1, (
        f"old_crossfade_notify count={p.count(old_crossfade_notify)}"
    )
    new_crossfade_notify = (
        "def _mpdcrossfadeidle_notify(partition):\n"
        "    # 実MPD (Partition::EmitIdle) はcrossfade/mixrampdb/mixrampdelayの\n"
        "    # options idle通知を変更元パーティションのクライアントにのみscopeする。\n"
        "    # mpdidlemixerpartition-patch.pyのmixer/output向け個別配送と同じProxyCall\n"
        "    # 直接tell()を、当該パーティションのセッションだけへ使う\n"
        "    # (mpdcrossfadeidlepartition-patch.py)。\n"
        "    from pykka.messages import ProxyCall\n"
        "\n"
        "    for actor_ref in translator.partition_idle_targets(partition):\n"
        "        actor_ref.tell(\n"
        '            ProxyCall(attr_path=["on_event"], args=["options"], kwargs={})\n'
        "        )\n"
    )
    p = p.replace(old_crossfade_notify, new_crossfade_notify, 1)

    old_crossfade = (
        "        Sets crossfading between songs.\n"
        '    """\n'
        "    partition = translator.partition_get(id(context.session))\n"
        "    translator.set_crossfade(seconds, partition)\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    assert p.count(old_crossfade) == 1, f"old_crossfade count={p.count(old_crossfade)}"
    new_crossfade = (
        "        Sets crossfading between songs.\n"
        '    """\n'
        "    partition = translator.partition_get(id(context.session))\n"
        "    translator.set_crossfade(seconds, partition)\n"
        "    _mpdcrossfadeidle_notify(partition)\n"
    )
    p = p.replace(old_crossfade, new_crossfade, 1)

    old_mixrampdb = (
        "    https://sourceforge.net/projects/mixramp/\n"
        '    """\n'
        "    translator.set_mixrampdb(decibels, translator.partition_get(id(context.session)))\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    assert p.count(old_mixrampdb) == 1, f"old_mixrampdb count={p.count(old_mixrampdb)}"
    new_mixrampdb = (
        "    https://sourceforge.net/projects/mixramp/\n"
        '    """\n'
        "    partition = translator.partition_get(id(context.session))\n"
        "    translator.set_mixrampdb(decibels, partition)\n"
        "    _mpdcrossfadeidle_notify(partition)\n"
    )
    p = p.replace(old_mixrampdb, new_mixrampdb, 1)

    old_mixrampdelay = (
        "        value of \"nan\" disables MixRamp overlapping and falls back to\n"
        "        crossfading.\n"
        '    """\n'
        "    translator.set_mixrampdelay(seconds, translator.partition_get(id(context.session)))\n"
        "    _mpdcrossfadeidle_notify()\n"
    )
    assert p.count(old_mixrampdelay) == 1, f"old_mixrampdelay count={p.count(old_mixrampdelay)}"
    new_mixrampdelay = (
        "        value of \"nan\" disables MixRamp overlapping and falls back to\n"
        "        crossfading.\n"
        '    """\n'
        "    partition = translator.partition_get(id(context.session))\n"
        "    translator.set_mixrampdelay(seconds, partition)\n"
        "    _mpdcrossfadeidle_notify(partition)\n"
    )
    p = p.replace(old_mixrampdelay, new_mixrampdelay, 1)

    old_replaygain_notify = (
        "def _mpdreplaygain_notify():\n"
        "    # session.py への import サイクルを避けるため呼び出し時に遅延import する\n"
        "    # (mpdmount-patch.py の _mpdmount_notify と同じ理由)。\n"
        "    from mopidy import listener\n"
        "    from mopidy_mpd import session as mpd_session\n"
        "\n"
        '    listener.send(mpd_session.MpdSession, "options")\n'
    )
    assert p.count(old_replaygain_notify) == 1, (
        f"old_replaygain_notify count={p.count(old_replaygain_notify)}"
    )
    new_replaygain_notify = (
        "def _mpdreplaygain_notify(partition):\n"
        "    # crossfade/mixrampdb/mixrampdelayと同じ理由・機構でパーティション限定\n"
        "    # 配送する (mpdcrossfadeidlepartition-patch.py、_mpdcrossfadeidle_notify\n"
        "    # 参照)。\n"
        "    from pykka.messages import ProxyCall\n"
        "\n"
        "    for actor_ref in translator.partition_idle_targets(partition):\n"
        "        actor_ref.tell(\n"
        '            ProxyCall(attr_path=["on_event"], args=["options"], kwargs={})\n'
        "        )\n"
    )
    p = p.replace(old_replaygain_notify, new_replaygain_notify, 1)

    old_replay_gain_mode = (
        "    if mode not in _MPD_REPLAY_GAIN_MODES:\n"
        '        raise exceptions.MpdArgError("Unrecognized replay gain mode")\n'
        "    translator.set_replay_gain_mode(mode, translator.partition_get(id(context.session)))\n"
        "    _mpdreplaygain_notify()\n"
    )
    assert p.count(old_replay_gain_mode) == 1, (
        f"old_replay_gain_mode count={p.count(old_replay_gain_mode)}"
    )
    new_replay_gain_mode = (
        "    if mode not in _MPD_REPLAY_GAIN_MODES:\n"
        '        raise exceptions.MpdArgError("Unrecognized replay gain mode")\n'
        "    partition = translator.partition_get(id(context.session))\n"
        "    translator.set_replay_gain_mode(mode, partition)\n"
        "    _mpdreplaygain_notify(partition)\n"
    )
    p = p.replace(old_replay_gain_mode, new_replay_gain_mode, 1)

    open(pp, "w").write(p)
    print(
        "patched playback.py: crossfade/mixrampdb/mixrampdelay/replay_gain_mode の"
        "options idle通知を変更元パーティションのセッションだけへ絞り込み"
    )
