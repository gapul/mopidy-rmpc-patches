# mopidy_mpd/translator.py の channels.py (client-to-client messaging) 用揮発性ストア
# _channel_subscriptions / _channel_actor_refs / _channel_messages (mpdchannels-patch.py
# が追加) は、mpdurimaprace-patch.py が MpdUriMapper で修正したのと全く同じ理由で
# スレッド安全性が無い: これら3つの module-level dict は全クライアント接続 (各々別の
# OSスレッドで動く pykka.ThreadingActor = MpdSession) から一切のロック無しで共有
# read/write されている。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# mopidy_mpd のコード品質を再調査して発見した。
#
# 実害: `channel_list()` は
#   for subs in _channel_subscriptions.values()
# 、`channel_push_message()` は
#   for session_id, subs in _channel_subscriptions.items()
# という dict の内容をその場で走査するループを持つ。一方、`channel_cleanup()` は
# 接続切断のたび (session.py の on_stop から channels.py 未使用のクライアントも含め
# **無条件**に) `_channel_subscriptions.pop(session_id, None)` で dict から削除する。
# CPython の dict は「走査中に要素数が変化する(挿入/削除)」と `RuntimeError:
# dictionary changed size during iteration` を送出する仕様のため、あるクライアント
# 接続のスレッドが `channels`/`sendmessage` コマンドでこれらの走査を実行している
# 最中に、**別の**クライアント接続のスレッドが切断する (subscribeの有無を問わず
# 起こる、ごくありふれた操作) と走査側スレッドで `RuntimeError` が飛ぶ。
# `RuntimeError` は `exceptions.MpdAckError` のサブクラスではないため
# `dispatcher.py` の `_catch_mpd_ack_errors_filter` に捕捉されず、`session.py` にも
# 保護が無いため pykka アクターの外まで伝播し `network.LineProtocol.on_failure`
# (`self.connection.stop("Actor failed.")`) に到達、ACK エラーが一切返らずその
# 接続の TCP セッションが問答無用で切断される。トリガ条件は「2本以上の MPD 接続が
# 同時に張られている」だけで良く、一方が `channels`/`sendmessage` を実行中、
# もう一方(subscribe/sendmessageを一切使っていないクライアントでもよい)が
# 切断する、という組み合わせで発現する。
#
# 修正: mpdurimaprace-patch.py と全く同じ流儀で、translator.py にモジュールレベルの
# `threading.RLock()` (`_channel_lock`) を追加し、3つの dict を読み書きする
# channel_subscribe/channel_unsubscribe/channel_list/channel_push_message/
# channel_read_messages/channel_cleanup の本体を `with _channel_lock:` で直列化する。
# これらの関数はいずれもローカルの dict 操作のみで完結しバックエンドへの
# ネットワーク呼び出し (pykka future の .get() 等) を含まないため、
# mpdurimaprace-patch.py が警戒した「listall事案のような長時間ブロック」の懸念は無い。

p = "mopidy_mpd/translator.py"
s = open(p).read()

MARKER = "_channel_lock"
if MARKER in s:
    print("mpdchannelrace already applied to translator.py, skip")
else:
    old = (
        "_channel_subscriptions = {}\n"
        "_channel_actor_refs = {}\n"
        "_channel_messages = {}\n"
        "\n"
        "\n"
        "def channel_subscribe(session_id, channel, actor_ref):\n"
        "    subs = _channel_subscriptions.setdefault(session_id, set())\n"
        "    if channel in subs:\n"
        "        return False\n"
        "    subs.add(channel)\n"
        "    _channel_actor_refs[session_id] = actor_ref\n"
        "    return True\n"
        "\n"
        "\n"
        "def channel_unsubscribe(session_id, channel):\n"
        "    subs = _channel_subscriptions.get(session_id)\n"
        "    if not subs or channel not in subs:\n"
        "        return False\n"
        "    subs.discard(channel)\n"
        "    return True\n"
        "\n"
        "\n"
        "def channel_list():\n"
        "    names = set()\n"
        "    for subs in _channel_subscriptions.values():\n"
        "        names.update(subs)\n"
        "    return sorted(names)\n"
        "\n"
        "\n"
        "def channel_push_message(channel, text):\n"
        "    # 戻り値は実際にメッセージを受け取ったセッションの ActorRef 一覧。\n"
        "    # sendmessage() はこれを使って on_event('message') を対象セッションだけに\n"
        "    # 送る (無関係なセッションを idle から余分に起こさない)。\n"
        "    targets = []\n"
        "    for session_id, subs in _channel_subscriptions.items():\n"
        "        if channel in subs:\n"
        "            _channel_messages.setdefault(session_id, []).append((channel, text))\n"
        "            actor_ref = _channel_actor_refs.get(session_id)\n"
        "            if actor_ref is not None:\n"
        "                targets.append(actor_ref)\n"
        "    return targets\n"
        "\n"
        "\n"
        "def channel_read_messages(session_id):\n"
        "    return _channel_messages.pop(session_id, [])\n"
        "\n"
        "\n"
        "def channel_cleanup(session_id):\n"
        "    _channel_subscriptions.pop(session_id, None)\n"
        "    _channel_actor_refs.pop(session_id, None)\n"
        "    _channel_messages.pop(session_id, None)\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "_channel_subscriptions = {}\n"
        "_channel_actor_refs = {}\n"
        "_channel_messages = {}\n"
        "# 全クライアント接続(各々別スレッドのMpdSessionアクター)が上記3つのdictを\n"
        "# 共有するため、読み書きはRLockで直列化する(mpdchannelrace-patch.py)。\n"
        "_channel_lock = threading.RLock()\n"
        "\n"
        "\n"
        "def channel_subscribe(session_id, channel, actor_ref):\n"
        "    with _channel_lock:\n"
        "        subs = _channel_subscriptions.setdefault(session_id, set())\n"
        "        if channel in subs:\n"
        "            return False\n"
        "        subs.add(channel)\n"
        "        _channel_actor_refs[session_id] = actor_ref\n"
        "        return True\n"
        "\n"
        "\n"
        "def channel_unsubscribe(session_id, channel):\n"
        "    with _channel_lock:\n"
        "        subs = _channel_subscriptions.get(session_id)\n"
        "        if not subs or channel not in subs:\n"
        "            return False\n"
        "        subs.discard(channel)\n"
        "        return True\n"
        "\n"
        "\n"
        "def channel_list():\n"
        "    with _channel_lock:\n"
        "        names = set()\n"
        "        for subs in _channel_subscriptions.values():\n"
        "            names.update(subs)\n"
        "        return sorted(names)\n"
        "\n"
        "\n"
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
        "\n"
        "\n"
        "def channel_read_messages(session_id):\n"
        "    with _channel_lock:\n"
        "        return _channel_messages.pop(session_id, [])\n"
        "\n"
        "\n"
        "def channel_cleanup(session_id):\n"
        "    with _channel_lock:\n"
        "        _channel_subscriptions.pop(session_id, None)\n"
        "        _channel_actor_refs.pop(session_id, None)\n"
        "        _channel_messages.pop(session_id, None)\n"
    )
    s = s.replace(old, new, 1)

    # import threading (translator.py は素の状態では threading を import していない。
    # 既存の import 順 datetime/logging/re/time のアルファベット順に合わせ re の後に挿入)
    import_anchor = "import re\nimport time\n"
    assert s.count(import_anchor) == 1, f"import_anchor count={s.count(import_anchor)}"
    s = s.replace(import_anchor, "import re\nimport threading\nimport time\n", 1)

    open(p, "w").write(s)
    print(
        "patched translator.py: channels.py用の購読/メッセージ揮発性ストアが"
        "全クライアント接続間でロック無しに共有され、あるクライアントの"
        "channels/sendmessage実行中に別クライアントが切断するとdict走査中の"
        "変更でRuntimeErrorが発生し無関係な接続まで切断されてしまう不具合を修正 "
        "(threading.RLockでdict操作を直列化、mpdurimaprace-patch.pyと同じ流儀)"
    )
