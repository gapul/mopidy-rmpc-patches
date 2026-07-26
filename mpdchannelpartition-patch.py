# mpdchannels-patch.py が実装した client-to-client messaging
# (subscribe/unsubscribe/channels/readmessages/sendmessage) は、購読・チャンネル一覧・
# メッセージ配送のいずれもパーティション (partition.py, mpdpartition-patch.py) を一切
# 考慮せず、translator.py の _channel_subscriptions をサーバー全体で横断的に走査していた。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが (general-purposeサブエージェント
# への調査委任を経て) 新規発見した項目。
#
# 具体例: クライアントAが `newpartition work` → `partition work` → `subscribe foo` で
# パーティション"work"上でチャンネル"foo"を購読する。クライアントBは"default"のまま
# `channels` を叩くと、"work"側でしか購読されていない"foo"が見えてしまう。同様にBが
# `sendmessage foo "hi"` を送ると、無関係な別パーティションのAへメッセージが配送され
# 成功応答(OK)になってしまう。
#
# 実MPD仕様 (MusicPlayerDaemon/MPD, WebFetch/gh api で src/command/MessageCommands.cxx を
# 実際に取得し確認): `handle_channels()`/`handle_send_message()` はいずれも
# `client.GetPartition().clients` (自分の所属パーティションのクライアント集合) のみを
# 走査する。他パーティションのクライアントが購読していても対象外であり、send_messageで
# 送信先がゼロなら実MPDでも既存のmopidy実装同様 ACK_ERROR_NO_EXIST
# "nobody is subscribed to this channel" を返す (この部分は既に正しい)。
# `Client::SetPartition()` (src/client/Client.cxx) は自分が所属する
# `partition->clients` の intrusive list を差し替えるだけで購読自体は破棄しないため、
# 「どのパーティション所属として扱われるか」は購読時点ではなく `channels`/`sendmessage`
# 呼び出し時点のクライアントの"現在の"所属で動的に決まる (partition.pyのpartition_get()と
# 同じ、購読時に固定しない設計が正しい)。
#
# rmpc本体 (mierak/rmpc, WebFetch/gh search codeで実際に確認) は subscribe/channels/
# sendmessage/readmessages を単なる飾りではなく実IPC基盤として使用している:
# rmpcd/src/lua/lualib/mpd/c2c.rs がLuaスクリプト向けc2c APIを実装し、
# rmpc/src/core/command.rs の `client.send_message()` でCLIから直接メッセージ送信できる。
# rmpcは `--partition` オプションで複数インスタンスをパーティション単位に隔離する設計
# (rmpc-mpd/src/client.rs) を持つため、複数rmpc/rmpcdインスタンスをそれぞれ別
# パーティションで動かすマルチルーム構成では、本来隔離されるべきc2cメッセージ/
# チャンネル一覧が現状漏れ、無関係な別パーティションのLuaスクリプトへ誤配送・傍受されうる。
#
# 修正: translator.channel_list()/channel_push_message() に partition 引数を追加し、
# 各購読セッションの所属パーティション (partition_get(session_id)、呼び出し時点で動的に
# 解決、mpdoutputpartitionempty-patch.pyと同じ流儀) が一致するものだけを対象にする。
# subscribe/unsubscribe/readmessages はもともとセッション単位で自己完結しており
# パーティションの影響を受けないため無変更。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "def channel_list(partition):"
if MARKER_T in t:
    print("translator.py already patched for channel partition scoping, skip")
else:
    old_channel_list = (
        "def channel_list():\n"
        "    with _channel_lock:\n"
        "        names = set()\n"
        "        for subs in _channel_subscriptions.values():\n"
        "            names.update(subs)\n"
        "        return sorted(names)\n"
    )
    assert t.count(old_channel_list) == 1, (
        f"old_channel_list count={t.count(old_channel_list)}"
    )
    new_channel_list = (
        "def channel_list(partition):\n"
        "    with _channel_lock:\n"
        "        names = set()\n"
        "        for session_id, subs in _channel_subscriptions.items():\n"
        "            if partition_get(session_id) == partition:\n"
        "                names.update(subs)\n"
        "        return sorted(names)\n"
    )
    t = t.replace(old_channel_list, new_channel_list, 1)

    old_push = (
        "def channel_push_message(channel, text):\n"
        "    # 戻り値は実際にメッセージを受け取ったセッションの ActorRef 一覧。\n"
        "    # sendmessage() はこれを使って on_event('message') を対象セッションだけに\n"
        "    # 送る (無関係なセッションを idle から余分に起こさない)。\n"
        "    with _channel_lock:\n"
        "        targets = []\n"
        "        for session_id, subs in _channel_subscriptions.items():\n"
        "            if channel in subs:\n"
        "                _channel_messages.setdefault(session_id, []).append((channel, text))\n"
        "                actor_ref = _channel_actor_refs.get(session_id)\n"
        "                if actor_ref is not None:\n"
        "                    targets.append(actor_ref)\n"
        "        return targets\n"
    )
    assert t.count(old_push) == 1, f"old_push count={t.count(old_push)}"
    new_push = (
        "def channel_push_message(partition, channel, text):\n"
        "    # 戻り値は実際にメッセージを受け取ったセッションの ActorRef 一覧。\n"
        "    # sendmessage() はこれを使って on_event('message') を対象セッションだけに\n"
        "    # 送る (無関係なセッションを idle から余分に起こさない)。実MPD同様、送信元と\n"
        "    # 同じパーティションに所属するセッションの購読だけを配送対象にする\n"
        "    # (MessageCommands.cxx handle_send_messageのclient.GetPartition().clients走査)。\n"
        "    with _channel_lock:\n"
        "        targets = []\n"
        "        for session_id, subs in _channel_subscriptions.items():\n"
        "            if channel in subs and partition_get(session_id) == partition:\n"
        "                _channel_messages.setdefault(session_id, []).append((channel, text))\n"
        "                actor_ref = _channel_actor_refs.get(session_id)\n"
        "                if actor_ref is not None:\n"
        "                    targets.append(actor_ref)\n"
        "        return targets\n"
    )
    t = t.replace(old_push, new_push, 1)
    open(tp, "w").write(t)
    print(
        "patched translator.py: channel_list()/channel_push_message() を"
        " パーティション単位に絞り込み"
    )

pp = "mopidy_mpd/protocol/channels.py"
s = open(pp).read()

MARKER_P = "translator.partition_get(id(context.session))"
if MARKER_P in s:
    print("channels.py already patched for channel partition scoping, skip")
else:
    old_channels_fn = (
        "    return [(\"channel\", name) for name in translator.channel_list()]\n"
    )
    assert s.count(old_channels_fn) == 1, f"old_channels_fn count={s.count(old_channels_fn)}"
    new_channels_fn = (
        "    return [\n"
        '        ("channel", name)\n'
        "        for name in translator.channel_list(\n"
        "            translator.partition_get(id(context.session))\n"
        "        )\n"
        "    ]\n"
    )
    s = s.replace(old_channels_fn, new_channels_fn, 1)

    old_sendmessage = (
        "    targets = translator.channel_push_message(channel, text)\n"
    )
    assert s.count(old_sendmessage) == 1, f"old_sendmessage count={s.count(old_sendmessage)}"
    new_sendmessage = (
        "    targets = translator.channel_push_message(\n"
        "        translator.partition_get(id(context.session)), channel, text\n"
        "    )\n"
    )
    s = s.replace(old_sendmessage, new_sendmessage, 1)
    open(pp, "w").write(s)
    print(
        "patched channels.py: channels()/sendmessage() を送信元セッションの"
        " パーティションで絞り込むよう変更"
    )
