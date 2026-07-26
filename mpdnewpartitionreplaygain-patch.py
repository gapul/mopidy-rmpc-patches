# newpartition (mpdpartition-patch.py) で作った新パーティションが、常に
# replay_gain_mode="off"で始まってしまう不具合。TODO/既知の残課題を全項目消化済み
# のため自走エージェントが(general-purposeサブエージェントへの調査委任を経て)
# 新規発見。
#
# 実MPD本体 (gh rawで確認):
#   - src/Partition.cxx Partition::Partition(name, src) (newpartition専用の
#     コピー元付きコンストラクタ) は `SetReplayGainMode(src.replay_gain_mode)`
#     を呼び、新パーティションの replay_gain_mode を作成元パーティション(src)の
#     現在値で初期化する。NEWS(ver 0.24.13)にも
#     「configuration: copy replay_gain_mode when creating a new partition」と
#     明記されている。
#   - src/command/PartitionCommands.cxx handle_newpartition() は
#     `instance.partitions.emplace_back(name, client.GetPartition())` で
#     呼び出しクライアントの現在所属パーティションをsrcとして渡す。
#   - 一方 `pc`(PlayerControl、crossfade/mixrampdb/mixrampdelay保持)は
#     同コンストラクタが委譲する基底コンストラクタ内で config.player(mpd.conf
#     の静的設定)から都度新規構築されるだけで、srcの実行時状態はコピーされない
#     (replay_gain_modeだけがsrcからの明示コピー対象という非対称仕様)。
#
# mpdplayercontrolpartition-patch.py はcrossfade/mixrampdb/mixrampdelay/
# replay_gain_modeの4値をパーティション名キーの辞書化したが、
# translator.partition_try_create()は_partitions.append(name)するだけで
# _replay_gain_mode[name]を一切初期化しないため、get_replay_gain_mode(name)は
# 常にフォールバック既定値"off"を返す。crossfade/mixrampdb/mixrampdelayを
# 「常にデフォルトに戻す」現状の実装は実MPDと一致しているが、replay_gain_mode
# だけは実MPDと異なり作成元パーティションの値を引き継ぐべきところ引き継げていない。
#
# BACKLOG.md全体を"newpartition"/"replay_gain"/"SetReplayGainMode"/
# "copy replay_gain_mode"で検索したが、直近のmpdplayercontrolpartition-patch.py/
# mpdcrossfadeidlepartition-patch.pyのエントリはcrossfade/mixrampdb/mixrampdelay/
# replay_gain_modeの「パーティション間の値の漏洩」「idle通知の漏洩」のみを扱って
# おり、newpartition作成時点でのreplay_gain_modeコピー漏れは既出無し・
# blocked指定も無しと確認。
#
# 修正: protocol/partition.pyのnewpartition()で呼び出しクライアントの現在
# 所属パーティション名をtranslator.partition_get(id(context.session))
# (mpdvolumepartition-patch.py等と同じ既存パターン)で取得し、
# translator.partition_try_create(name, source_partition)へ渡す。
# partition_try_create()は既存のロックスコープ内(TOCTOU安全性維持)で
# _replay_gain_mode[name] = _replay_gain_mode.get(source_partition, "off")
# を追加する。crossfade/mixrampdb/mixrampdelayは実MPD同様デフォルトのまま
# 変更しない。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER = 'def partition_try_create(name, source_partition="default"):'
if MARKER in t:
    print("translator.py already patched, skip")
else:
    old_try_create = (
        "def partition_try_create(name):\n"
        "    # newpartitionハンドラの存在確認+上限確認+作成を単一ロックで\n"
        "    # 直列化するTOCTOU対策 (mpdpartitiondeltoctou-patch.pyの\n"
        "    # partition_try_delete()と同じ流儀)。個別に呼ぶと、件数が上限未満\n"
        "    # であることを確認した直後・作成実行前に別接続が別名で作成すると\n"
        "    # 実際には上限を超えた個数のパーティションが存在してしまう。\n"
        "    with _partition_lock:\n"
        "        if name in _partitions:\n"
        '            return "exists"\n'
        "        if len(_partitions) >= 16:\n"
        '            return "too_many"\n'
        "        _partitions.append(name)\n"
        "        return None\n"
    )
    assert t.count(old_try_create) == 1, f"old_try_create count={t.count(old_try_create)}"
    new_try_create = (
        'def partition_try_create(name, source_partition="default"):\n'
        "    # newpartitionハンドラの存在確認+上限確認+作成を単一ロックで\n"
        "    # 直列化するTOCTOU対策 (mpdpartitiondeltoctou-patch.pyの\n"
        "    # partition_try_delete()と同じ流儀)。個別に呼ぶと、件数が上限未満\n"
        "    # であることを確認した直後・作成実行前に別接続が別名で作成すると\n"
        "    # 実際には上限を超えた個数のパーティションが存在してしまう。\n"
        "    with _partition_lock:\n"
        "        if name in _partitions:\n"
        '            return "exists"\n'
        "        if len(_partitions) >= 16:\n"
        '            return "too_many"\n'
        "        _partitions.append(name)\n"
        "        # 実MPD (src/Partition.cxx Partition::Partition(name, src)) は\n"
        "        # SetReplayGainMode(src.replay_gain_mode) で作成元パーティションの\n"
        "        # replay_gain_modeを新パーティションへコピーする\n"
        "        # (mpdnewpartitionreplaygain-patch.py)。crossfade/mixrampdb/\n"
        "        # mixrampdelayはPlayerControlがconfig.playerから都度新規構築される\n"
        "        # だけでsrcの実行時状態を引き継がないため対象外(既定値のままが正)。\n"
        '        _replay_gain_mode[name] = _replay_gain_mode.get(source_partition, "off")\n'
        "        return None\n"
    )
    assert new_try_create != old_try_create
    t = t.replace(old_try_create, new_try_create, 1)

    open(tp, "w").write(t)
    print("patched translator.py: partition_try_create()がsource_partitionのreplay_gain_modeを新パーティションへコピーするよう変更")

pp = "mopidy_mpd/protocol/partition.py"
p = open(pp).read()

MARKER_PP = "translator.partition_try_create(name, source_partition)"
if MARKER_PP in p:
    print("partition.py already patched, skip")
else:
    old_newpartition = (
        "    if not _mpdpartition_name_re.match(name):\n"
        '        raise exceptions.MpdArgError("bad name")\n'
        "    status = translator.partition_try_create(name)\n"
        '    if status == "too_many":\n'
        '        raise exceptions.MpdUnknownError("too many partitions")\n'
        '    if status == "exists":\n'
        '        raise exceptions.MpdExistError("name already exists")\n'
        '    _mpdpartition_notify("partition")\n'
    )
    assert p.count(old_newpartition) == 1, f"old_newpartition count={p.count(old_newpartition)}"
    new_newpartition = (
        "    if not _mpdpartition_name_re.match(name):\n"
        '        raise exceptions.MpdArgError("bad name")\n'
        "    source_partition = translator.partition_get(id(context.session))\n"
        "    status = translator.partition_try_create(name, source_partition)\n"
        '    if status == "too_many":\n'
        '        raise exceptions.MpdUnknownError("too many partitions")\n'
        '    if status == "exists":\n'
        '        raise exceptions.MpdExistError("name already exists")\n'
        '    _mpdpartition_notify("partition")\n'
    )
    p = p.replace(old_newpartition, new_newpartition, 1)

    open(pp, "w").write(p)
    print("patched partition.py: newpartition()が呼び出しクライアントの現在所属パーティションをsource_partitionとして渡すよう変更")
