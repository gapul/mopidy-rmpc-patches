# mpdchannels-patch.py が実装した client-to-client messaging (subscribe/sendmessage) には
# 実 MPD が持つ上限 (1クライアント辺りの購読チャンネル数、1クライアント辺りの未読
# メッセージ数) が一切無い。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て) 新規発見した項目。
#
# 実MPD仕様 (MusicPlayerDaemon/MPD, raw.githubusercontent.comで実際に取得し確認):
# src/client/Client.hxx: `static constexpr size_t MAX_SUBSCRIPTIONS = 16;` /
# `static constexpr size_t MAX_MESSAGES = 64;`。src/client/Subscribe.cxx の
# `Client::Subscribe()` は (1)チャンネル名不正 → INVALID、(2)`num_subscriptions >=
# MAX_SUBSCRIPTIONS` → FULL、(3)`subscriptions.insert().second`失敗(重複) → ALREADY、
# の順で判定する (FULL判定が重複判定より先。既に16件購読済みの状態で同じチャンネル名を
# 再度subscribeしてもALREADYではなくFULLになる)。src/command/MessageCommands.cxx の
# `handle_subscribe()` は FULL を `ACK_ERROR_EXIST`(56) + "subscription list is full" に
# マップする (ALREADY と同じエラーコード、メッセージのみ異なる)。`Client::PushMessage()`
# は `messages.size() >= MAX_MESSAGES` なら黙って false を返し (対象クライアントの
# キューにだけ積まない、ACKにはならない)、`handle_send_message()` は購読者全員へ配送を
# 試みた上で1人でも成功すれば送信元へOK、全員失敗(≒無購読 or 全員キュー満杯)なら
# `ACK_ERROR_NO_EXIST` "nobody is subscribed to this channel" を返す。
#
# 現状のmopidy_mpd (mpdchannels-patch.py 由来のtranslator.py実装) はいずれの上限も
# 実装しておらず、`_channel_subscriptions[session_id]`(購読チャンネル集合)も
# `_channel_messages[session_id]`(未読メッセージリスト)も無制限に増加できる。
# rmpc本体がchannels/sendmessageを実IPC基盤として使う設計(mpdchannelpartition-patch.py
# のコメント参照)であることを踏まえると、購読側の実装バグや悪意あるクライアントが
# 無制限にサーバー側メモリを消費させられる。
#
# 修正: translator.py に実MPDと同じ定数 (_MPD_MAX_CHANNEL_SUBSCRIPTIONS=16 /
# _MPD_MAX_CHANNEL_MESSAGES=64) を追加し、
# (1) channel_subscribe() は判定順を実MPDと同じ FULL→重複 の順にし、"ok"/"already"/
#     "full" の3値文字列を返すよう変更 (mpdurimaprace-patch.py以来のRLockでの直列化は
#     そのまま維持)。
# (2) channel_push_message() は対象セッションごとにキュー長が上限未満の場合のみ
#     メッセージを積んでtargetsに含め (実MPDのPushMessage同様、上限到達分だけを
#     黙ってスキップし他の対象への配送・返り値には影響しない)。
# channels.py の subscribe() は3値文字列に応じてACK_ERROR_EXIST(56)の2種のメッセージを
# 出し分ける。sendmessage()側はtargetsが空ならACK(既存実装のまま、上限到達で
# 全員スキップされた場合も自然にこの分岐に落ちる)。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER_T = "_MPD_MAX_CHANNEL_SUBSCRIPTIONS"
if MARKER_T in t:
    print("mpdchannellimit already applied to translator.py, skip")
else:
    old_const = (
        "_channel_lock = threading.RLock()\n"
    )
    assert t.count(old_const) == 1, f"old_const count={t.count(old_const)}"
    new_const = (
        "_channel_lock = threading.RLock()\n"
        "# 実MPD (src/client/Client.hxx) と同じ上限。\n"
        "_MPD_MAX_CHANNEL_SUBSCRIPTIONS = 16\n"
        "_MPD_MAX_CHANNEL_MESSAGES = 64\n"
    )
    t = t.replace(old_const, new_const, 1)

    old_subscribe = (
        "def channel_subscribe(session_id, channel, actor_ref):\n"
        "    with _channel_lock:\n"
        "        subs = _channel_subscriptions.setdefault(session_id, set())\n"
        "        if channel in subs:\n"
        "            return False\n"
        "        subs.add(channel)\n"
        "        _channel_actor_refs[session_id] = actor_ref\n"
        "        return True\n"
    )
    assert t.count(old_subscribe) == 1, f"old_subscribe count={t.count(old_subscribe)}"
    new_subscribe = (
        "def channel_subscribe(session_id, channel, actor_ref):\n"
        "    # 実MPDのClient::Subscribe()と同じ判定順: 上限到達チェックが重複チェック\n"
        "    # より先 (既に上限まで購読済みの状態で同じチャンネル名を再度subscribeしても\n"
        "    # \"already\"ではなく\"full\"になる)。\n"
        "    with _channel_lock:\n"
        "        subs = _channel_subscriptions.setdefault(session_id, set())\n"
        "        if len(subs) >= _MPD_MAX_CHANNEL_SUBSCRIPTIONS:\n"
        "            return \"full\"\n"
        "        if channel in subs:\n"
        "            return \"already\"\n"
        "        subs.add(channel)\n"
        "        _channel_actor_refs[session_id] = actor_ref\n"
        "        return \"ok\"\n"
    )
    t = t.replace(old_subscribe, new_subscribe, 1)

    old_push = (
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
    assert t.count(old_push) == 1, f"old_push count={t.count(old_push)}"
    new_push = (
        "def channel_push_message(partition, channel, text):\n"
        "    # 戻り値は実際にメッセージを受け取ったセッションの ActorRef 一覧。\n"
        "    # sendmessage() はこれを使って on_event('message') を対象セッションだけに\n"
        "    # 送る (無関係なセッションを idle から余分に起こさない)。実MPD同様、送信元と\n"
        "    # 同じパーティションに所属するセッションの購読だけを配送対象にする\n"
        "    # (MessageCommands.cxx handle_send_messageのclient.GetPartition().clients走査)。\n"
        "    # 実MPDのClient::PushMessage()と同様、対象セッションの未読メッセージ数が\n"
        "    # 上限に達している場合はそのセッションへの配送だけを黙ってスキップする\n"
        "    # (ACKにはならない。他の対象への配送・戻り値には影響しない)。\n"
        "    with _channel_lock:\n"
        "        targets = []\n"
        "        for session_id, subs in _channel_subscriptions.items():\n"
        "            if channel in subs and partition_get(session_id) == partition:\n"
        "                messages = _channel_messages.setdefault(session_id, [])\n"
        "                if len(messages) >= _MPD_MAX_CHANNEL_MESSAGES:\n"
        "                    continue\n"
        "                messages.append((channel, text))\n"
        "                actor_ref = _channel_actor_refs.get(session_id)\n"
        "                if actor_ref is not None:\n"
        "                    targets.append(actor_ref)\n"
        "        return targets\n"
    )
    t = t.replace(old_push, new_push, 1)
    open(tp, "w").write(t)
    print(
        "patched translator.py: channel_subscribe()に購読数上限(16)、"
        "channel_push_message()に未読メッセージ数上限(64、対象毎)を追加"
    )

pp = "mopidy_mpd/protocol/channels.py"
s = open(pp).read()

MARKER_P = "subscription list is full"
if MARKER_P in s:
    print("channels.py already patched for channel subscription limit, skip")
else:
    old_subscribe_fn = (
        "    if not _mpdchannels_name_re.match(channel):\n"
        "        raise exceptions.MpdArgError(\"invalid channel name\")\n"
        "    if not translator.channel_subscribe(\n"
        "        id(context.session), channel, context.session.actor_ref\n"
        "    ):\n"
        "        raise exceptions.MpdExistError(\"already subscribed to this channel\")\n"
        "    _mpdchannels_notify(\"subscription\")\n"
    )
    assert s.count(old_subscribe_fn) == 1, f"old_subscribe_fn count={s.count(old_subscribe_fn)}"
    new_subscribe_fn = (
        "    if not _mpdchannels_name_re.match(channel):\n"
        "        raise exceptions.MpdArgError(\"invalid channel name\")\n"
        "    result = translator.channel_subscribe(\n"
        "        id(context.session), channel, context.session.actor_ref\n"
        "    )\n"
        "    if result == \"full\":\n"
        "        raise exceptions.MpdExistError(\"subscription list is full\")\n"
        "    if result == \"already\":\n"
        "        raise exceptions.MpdExistError(\"already subscribed to this channel\")\n"
        "    _mpdchannels_notify(\"subscription\")\n"
    )
    s = s.replace(old_subscribe_fn, new_subscribe_fn, 1)
    open(pp, "w").write(s)
    print(
        "patched channels.py: subscribe()が購読数上限到達時に"
        " ACK_ERROR_EXIST \"subscription list is full\" を返すよう変更"
    )
