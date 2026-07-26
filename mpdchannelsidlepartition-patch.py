# subscribe/unsubscribe (mpdchannels-patch.py) が発火する idle "subscription" 通知が、
# 依然 `_mpdchannels_notify("subscription")` = `mopidy.listener.send(MpdSession, ...)` に
# よる無条件全パーティション broadcast のままで未対応だった不具合。mpdchannels-patch.py
# 自身のコメントは「idle "subscription" は実 MPD の idle_add(IDLE_SUBSCRIPTION) 同様、
# 全セッションへの無条件ブロードキャストが正しい仕様」と明記しているが、これは実 MPD
# ソースの誤読だった。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て) 新規発見した項目。
#
# 実MPD本体 (gh raw、MusicPlayerDaemon/MPD) を実際に確認: src/client/Subscribe.cxx の
# `Client::Subscribe()`/`Client::Unsubscribe()` はいずれも `partition->EmitIdle(
# IDLE_SUBSCRIPTION)` を呼ぶ。`Partition::EmitIdle` は src/Partition.hxx のdocstring
# 通り「このパーティションの全クライアントへ idle イベントを発行する」自パーティション
# 限定のメソッドであり、真にグローバルな `idle_add()`(src/Idle.cxx、
# `global_instance->EmitIdle(flags)`)とは別物 (`IDLE_SUBSCRIPTION` は idle_add() 側では
# 一切使われていない)。mixer/output (mpdidlemixerpartition-patch.py) や
# crossfade/mixrampdb/mixrampdelay/replay_gain_mode (mpdcrossfadeidlepartition-patch.py)
# の options idle 通知で既に確認済みなのと全く同じ `Partition::EmitIdle` 機構であり、
# subscription だけがこの対応から漏れていた。
# (`IDLE_MESSAGE` = idle "message" はセッション単位の別機構 `Client::IdleAdd()` であり、
# こちらは mpdchannels-patch.py の `_mpdchannels_notify_targeted` が既に正しく個別配送
# 対応済み。mpdchannelpartition-patch.py は channels/sendmessage の「購読データの
# 可視性」をパーティション単位に絞り込んだが、そちらは今回の「subscribe/unsubscribe
# 自体が発火する idle 通知の配送範囲」とは別軸で、この bug には触れていない)。
#
# 実害: rmpc は `--partition` オプションで複数パーティションを跨いだマルチルーム的な
# 構成に対応しており、各パーティションで `idle` に入りっぱなしの接続を持つ。パーティション
# A(default)のクライアントが subscribe/unsubscribe すると、無関係なパーティション
# B(newpartition)で `idle subscription`(または引数無し `idle`)待機中のrmpc等が誤って
# 起床する (自身の channels/readmessages は無変更のまま)。クラッシュや切断は起きないが
# 実MPD仕様違反かつ無駄な起床。
#
# 修正: mpdcrossfadeidlepartition-patch.py が確立した
# `translator.partition_idle_targets(partition)` (任意のパーティション名に属する
# セッションの actor_ref 一覧を返す既存の汎用ヘルパー) と、mpdchannels-patch.py 自身が
# 既に持つ `_mpdchannels_notify_targeted()` (pykka ProxyCall 直接 tell() による個別配送)
# を組み合わせるだけで、新規ヘルパーの追加は不要。subscribe()/unsubscribe() の
# `_mpdchannels_notify("subscription")` を
# `_mpdchannels_notify_targeted(translator.partition_idle_targets(partition), "subscription")`
# に置き換える (呼び出し元で計算済みの partition を変数へ束ねて渡すだけ)。

pp = "mopidy_mpd/protocol/channels.py"
s = open(pp).read()

MARKER = "# mpdchannelsidlepartition-patch.py"
if MARKER in s:
    print("channels.py already patched (mpdchannelsidlepartition), skip")
else:
    old_subscribe = (
        "    if not _mpdchannels_name_re.match(channel):\n"
        '        raise exceptions.MpdArgError("invalid channel name")\n'
        "    result = translator.channel_subscribe(\n"
        "        id(context.session), channel, context.session.actor_ref\n"
        "    )\n"
        '    if result == "full":\n'
        '        raise exceptions.MpdExistError("subscription list is full")\n'
        '    if result == "already":\n'
        '        raise exceptions.MpdExistError("already subscribed to this channel")\n'
        '    _mpdchannels_notify("subscription")\n'
    )
    assert s.count(old_subscribe) == 1, f"old_subscribe count={s.count(old_subscribe)}"
    new_subscribe = (
        "    if not _mpdchannels_name_re.match(channel):\n"
        '        raise exceptions.MpdArgError("invalid channel name")\n'
        "    result = translator.channel_subscribe(\n"
        "        id(context.session), channel, context.session.actor_ref\n"
        "    )\n"
        '    if result == "full":\n'
        '        raise exceptions.MpdExistError("subscription list is full")\n'
        '    if result == "already":\n'
        '        raise exceptions.MpdExistError("already subscribed to this channel")\n'
        "    # mpdchannelsidlepartition-patch.py: idle \"subscription\" を発火元セッションの\n"
        "    # パーティションだけへ絞り込む (実MPD Partition::EmitIdle 相当)。\n"
        "    partition = translator.partition_get(id(context.session))\n"
        "    _mpdchannels_notify_targeted(\n"
        '        translator.partition_idle_targets(partition), "subscription"\n'
        "    )\n"
    )
    s = s.replace(old_subscribe, new_subscribe, 1)

    old_unsubscribe = (
        "    if not translator.channel_unsubscribe(id(context.session), channel):\n"
        '        raise exceptions.MpdNoExistError("not subscribed to this channel")\n'
        '    _mpdchannels_notify("subscription")\n'
    )
    assert s.count(old_unsubscribe) == 1, f"old_unsubscribe count={s.count(old_unsubscribe)}"
    new_unsubscribe = (
        "    if not translator.channel_unsubscribe(id(context.session), channel):\n"
        '        raise exceptions.MpdNoExistError("not subscribed to this channel")\n'
        "    # mpdchannelsidlepartition-patch.py: idle \"subscription\" を発火元セッションの\n"
        "    # パーティションだけへ絞り込む (実MPD Partition::EmitIdle 相当)。\n"
        "    partition = translator.partition_get(id(context.session))\n"
        "    _mpdchannels_notify_targeted(\n"
        '        translator.partition_idle_targets(partition), "subscription"\n'
        "    )\n"
    )
    s = s.replace(old_unsubscribe, new_unsubscribe, 1)

    open(pp, "w").write(s)
    print(
        "patched channels.py: subscribe()/unsubscribe() の idle \"subscription\" 通知を"
        "発火元パーティションのセッションだけへ絞り込み"
    )
