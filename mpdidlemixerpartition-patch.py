# mixer/output idle 通知が全パーティションへ無条件ブロードキャストされる不具合を修正。
#
# mpdvolumepartition-patch.py/mpdoutputpartition-patch.pyは唯一の仮想出力"Mute"の
# 所属パーティション(translator.output_partition_get("Mute"))と自セッションの所属
# (translator.partition_get(id(context.session)))が一致する場合のみgetvol/setvol/
# volume/enableoutput/disableoutput/toggleoutput/outputset/outputsが実際にmixer状態を
# 読み書きするよう既に絞り込み済み (非所有時: setvolは暗黙no-opでOK、volumeはACK No
# mixer)。しかしこれらの操作が実際にcontext.core.mixer経由でvolume_changed/mute_changed
# を発火させた際、actor.py MpdFrontend.on_event()は_CORE_EVENTS_TO_IDLE_SUBSYSTEMS
# ("volume_changed":"mixer", "mute_changed":"output")を経由してsend_idle()を呼ぶだけで、
# send_idle()はmopidy.listener.send(session.MpdSession, subsystem)により接続中の
# 全MpdSessionへ無条件broadcastする。所有パーティションのクライアントがsetvol等で
# 実際にmixerを操作すると、非所有パーティションで`idle mixer`/`idle output`を購読中の
# 無関係なクライアントまで誤って起床してしまう(そのクライアント自身のgetvolは空応答の
# ままなのに、である)。
#
# 実MPD本体(gh raw、MusicPlayerDaemon/MPD)を実際に確認しこの非対称を特定:
# - src/Partition.cxx Partition::OnMixerVolumeChanged()/OnMixerChanged() はどちらも
#   自パーティション限定の`EmitIdle(IDLE_MIXER)`のみを呼ぶ(Partition::EmitIdleは
#   Partition.hxxで自パーティションのidle_monitorのみを操作、他パーティションのクライアント
#   には一切通知しない)。
# - src/output/OutputCommand.cxx audio_output_enable_index()/disable_index()/
#   toggle_index()、src/command/OutputCommands.cxx handle_outputset()も全て
#   `partition.EmitIdle(IDLE_OUTPUT)`(コマンドを発行したクライアント自身の
#   パーティション限定、CheckPartitionOutput()が非所有出力へのアクセス自体を先に
#   弾くため必然的に所有パーティションのみになる)。
# - 直近の実MPDコミット(2026-07-17, d9f2c3666dfcf1483598e88416958445a6e4ccff
#   "output/MultipleOutputs: install new MixerListener on moveoutput") のログ文言
#   "This finally fixes 'mixer' idle events on non-default partitions. Previously,
#   the MixerListener always pointed to the initial (default) partition." が、まさに
#   この「mixer idleが本来のパーティションを無視して漏れる」バグ自体が実MPD側でも
#   直近まで存在した実例であることを裏付けている。
#
# 一方、src/command/PartitionCommands.cxx handle_moveoutput()自体が発火するidle
# "output"は`instance.EmitIdle(IDLE_OUTPUT)`(Instance::OnIdle()が全パーティションを
# 走査してEmitIdleする、Instance.cxx確認済み)であり、これは意図的に全パーティション
# broadcastが正しい(出力の所属パーティションが変わったこと自体は全体に関わるため)。
# partition.py(mpdpartition-patch.py)の_mpdpartition_notify("output")は既にこの
# 全体broadcastと同じ機構(mopidy.listener.send)を使っており、そちらは対象外
# (今回のスコープはvolume_changed/mute_changedというmixer実操作由来のidleのみ)。
#
# 修正: channels.pyの_mpdchannels_notify_targeted(実MPDのClient::PushMessage()相当、
# メッセージ受信対象だけへ個別配送する既存機構)と同じpykka.messages.ProxyCallの
# 直接tell()を使い、volume_changed/mute_changedの2イベントだけ、唯一の仮想出力
# "Mute"の所属パーティションと同じパーティションに属するセッションのみへ個別配送する。
# 対象セッション一覧を得るため、channels.pyの購読時遅延登録(_channel_actor_refs)とは
# 別に、subscribe未実行の接続も含めた全セッションのactor_refをsession.pyのon_start/
# on_stopで無条件に登録/破棄する新規ストア(translator.py _session_actor_refs)を追加。
#
# 実機確認(TCP 6601、2接続A/B): newpartition p2 → B: partition p2 (Aはdefaultに残り
# Muteを所有)。修正前: A: idle mixer(blocking)中にB: setvol 50 → Aが誤って
# changed: mixerで起床(Aのgetvolは50を返す=Aは実際にはMute所有者なので影響が
# 逆転しているように見えるが、これは所有者Aが操作した側であり正しい対象。逆に
# B: idle mixer 購読中にA: setvol 50 を送ると、修正前はBも誤起床するが
# Bのgetvolは空応答のまま(Bは非所有)。これが実害のある漏れ)。修正後: 非所有
# パーティション(B)は起床せず、所有パーティション(A)のみ起床。同様にmoveoutput
# でMuteの所有をBへ移した後は逆にAが非所有側になり起床しなくなることを確認。
# regression: enableoutput/disableoutput/toggleoutputも同じ経路(mute_changed)で
# 正しく所有パーティションのみへ収束することを確認。他のsubsystem(player/playlist/
# options/stored_playlist/partition)は無変更(引き続き全broadcast、mopidy coreは
# パーティション毎に独立した再生状態を持たないため実MPDと異なりこちらは元々の
# 全体broadcastのままが正しい)。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_session_actor_refs = {}"
if MARKER_T in t:
    print("translator.py already patched (mpdidlemixerpartition), skip")
else:
    anchor = (
        "def output_partition_try_move(name, dest):\n"
        "    # moveoutputハンドラの現在の所属確認+比較+移動を単一ロックで\n"
        "    # 直列化するTOCTOU対策 (mpdpartitiondeltoctou-patch.pyの\n"
        "    # partition_try_delete()と同じ流儀)。個別に呼ぶと、2接続が\n"
        "    # ほぼ同時に異なるdestへmoveoutputを実行した場合、双方が\n"
        "    # 「現在の所属はdestと違う」ことを確認した直後に書き込むため\n"
        "    # 後勝ちの書き込みが先勝ちの結果を無条件で上書きし、ACKエラー\n"
        "    # 無しに一方の意図した移動がサイレントに失われる。\n"
        "    with _partition_lock:\n"
        "        if name not in _output_partition:\n"
        '            return "not_found"\n'
        "        if _output_partition[name] != dest:\n"
        "            _output_partition[name] = dest\n"
        '            return "moved"\n'
        '        return "unchanged"\n'
    )
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    addition = (
        "\n\n"
        "# mixer/output idle通知のパーティション絞り込み用: session id -> actor_ref。\n"
        "# _session_partitionと異なり、subscribe/partition switch未実行の接続も\n"
        "# mixer/output idle判定の対象になり得るため、session.pyのon_start/on_stopで\n"
        "# 無条件に登録/破棄する (mpdidlemixerpartition-patch.py)。\n"
        "_session_actor_refs = {}\n"
        "\n"
        "\n"
        "def session_register(session_id, actor_ref):\n"
        "    with _partition_lock:\n"
        "        _session_actor_refs[session_id] = actor_ref\n"
        "\n"
        "\n"
        "def session_unregister(session_id):\n"
        "    with _partition_lock:\n"
        "        _session_actor_refs.pop(session_id, None)\n"
        "\n"
        "\n"
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
    t = t.replace(anchor, anchor + addition, 1)
    open(tp, "w").write(t)
    print(
        "patched translator.py: mixer/output idle対象をパーティション所有者に"
        "絞り込むための_session_actor_refsストアを追加"
    )

sp = "mopidy_mpd/session.py"
s = open(sp).read()

MARKER_S = "translator.session_register"
if MARKER_S in s:
    print("session.py already patched (mpdidlemixerpartition), skip")
else:
    old_on_start = (
        "    def on_start(self):\n"
        '        logger.info("New MPD connection from %s", self.connection)\n'
        '        self.send_lines([f"OK MPD {protocol.VERSION}"])\n'
    )
    assert s.count(old_on_start) == 1, f"old_on_start count={s.count(old_on_start)}"
    new_on_start = (
        "    def on_start(self):\n"
        '        logger.info("New MPD connection from %s", self.connection)\n'
        "        # mixer/output idleの対象をパーティション所有者だけへ絞り込む\n"
        "        # ため (mpdidlemixerpartition-patch.py)、subscribe等の実行有無に\n"
        "        # 関わらず接続確立時から無条件でactor_refを登録する。\n"
        "        translator.session_register(id(self), self.actor_ref)\n"
        '        self.send_lines([f"OK MPD {protocol.VERSION}"])\n'
    )
    s = s.replace(old_on_start, new_on_start, 1)

    old_on_stop = (
        "    def on_stop(self):\n"
        "        # channels.py の client-to-client messaging 購読/未読メッセージを破棄\n"
        "        # (実 MPD の Client::UnsubscribeAll 相当)。\n"
        "        translator.channel_cleanup(id(self))\n"
        "        # partition.py のパーティション割り当てを破棄 (実MPDの\n"
        "        # ~Client()時のパーティション離脱相当)。\n"
        "        translator.partition_cleanup(id(self))\n"
        "        super().on_stop()\n"
    )
    assert s.count(old_on_stop) == 1, f"old_on_stop count={s.count(old_on_stop)}"
    new_on_stop = (
        "    def on_stop(self):\n"
        "        # channels.py の client-to-client messaging 購読/未読メッセージを破棄\n"
        "        # (実 MPD の Client::UnsubscribeAll 相当)。\n"
        "        translator.channel_cleanup(id(self))\n"
        "        # partition.py のパーティション割り当てを破棄 (実MPDの\n"
        "        # ~Client()時のパーティション離脱相当)。\n"
        "        translator.partition_cleanup(id(self))\n"
        "        # mixer/output idle対象追跡用のactor_ref登録を破棄\n"
        "        # (mpdidlemixerpartition-patch.py)。\n"
        "        translator.session_unregister(id(self))\n"
        "        super().on_stop()\n"
    )
    s = s.replace(old_on_stop, new_on_stop, 1)

    open(sp, "w").write(s)
    print(
        "patched session.py: on_start/on_stopでmixer/output idle対象追跡用の"
        "actor_ref登録/破棄を実行"
    )

ap = "mopidy_mpd/actor.py"
a = open(ap).read()

MARKER_A = "_send_idle_mixer_output"
if MARKER_A in a:
    print("actor.py already patched (mpdidlemixerpartition), skip")
else:
    old_dispatch = (
        "        if event not in _CORE_EVENTS_TO_IDLE_SUBSYSTEMS:\n"
        "            logger.warning(\n"
        '                "Got unexpected event: %s(%s)", event, ", ".join(kwargs)\n'
        "            )\n"
        "        else:\n"
        "            self.send_idle(_CORE_EVENTS_TO_IDLE_SUBSYSTEMS[event])\n"
    )
    assert a.count(old_dispatch) == 1, f"old_dispatch count={a.count(old_dispatch)}"
    new_dispatch = (
        "        if event not in _CORE_EVENTS_TO_IDLE_SUBSYSTEMS:\n"
        "            logger.warning(\n"
        '                "Got unexpected event: %s(%s)", event, ", ".join(kwargs)\n'
        "            )\n"
        "        else:\n"
        "            subsystem = _CORE_EVENTS_TO_IDLE_SUBSYSTEMS[event]\n"
        '            if subsystem in ("mixer", "output"):\n'
        "                self._send_idle_mixer_output(subsystem)\n"
        "            else:\n"
        "                self.send_idle(subsystem)\n"
    )
    a = a.replace(old_dispatch, new_dispatch, 1)

    old_send_idle = (
        "    def send_idle(self, subsystem):\n"
        "        if subsystem:\n"
        "            listener.send(session.MpdSession, subsystem)\n"
    )
    assert a.count(old_send_idle) == 1, f"old_send_idle count={a.count(old_send_idle)}"
    new_send_idle = old_send_idle + (
        "\n"
        "    def _send_idle_mixer_output(self, subsystem):\n"
        "        # 実MPD (Partition::OnMixerVolumeChanged/OnMixerChanged、\n"
        "        # OutputCommand.cxx audio_output_enable_index()等) はmixer/output\n"
        "        # のidle通知を、その出力を所有する1パーティションのクライアントにのみ\n"
        "        # scopeする (Partition::EmitIdleは自パーティションのクライアントの\n"
        "        # みへ配送)。mopidy_mpdは単一グローバルmixerしか無くパーティション毎の\n"
        "        # mixerを持たないため、mpdvolumepartition-patch.py/\n"
        "        # mpdoutputpartition-patch.pyが既に確立した「唯一の仮想出力\"Mute\"の\n"
        "        # 所属パーティション==自セッションの所属パーティション」判定を使い、\n"
        "        # 所有パーティションのセッションだけへchannels.pyの\n"
        "        # _mpdchannels_notify_targetedと同じProxyCall直接tell()で個別配送する\n"
        "        # (mopidy.listener.sendの無条件全セッションbroadcastは使わない)。\n"
        "        # moveoutput自体が発火するidle \"output\" (partition.py\n"
        "        # _mpdpartition_notify) は実MPDでもinstance.EmitIdle (全パーティション\n"
        "        # broadcast、PartitionCommands.cxx handle_moveoutput) であり対象外\n"
        "        # (この関数はvolume_changed/mute_changedからの呼び出し専用)。\n"
        "        from pykka.messages import ProxyCall\n"
        "\n"
        "        for actor_ref in translator.mixer_output_idle_targets():\n"
        "            actor_ref.tell(\n"
        '                ProxyCall(attr_path=["on_event"], args=[subsystem], kwargs={})\n'
        "            )\n"
    )
    a = a.replace(old_send_idle, new_send_idle, 1)

    open(ap, "w").write(a)
    print(
        "patched actor.py: volume_changed/mute_changedのidle通知をMute所有"
        "パーティションのセッションだけへ絞り込み"
    )
