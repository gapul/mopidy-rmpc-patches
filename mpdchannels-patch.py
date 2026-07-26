# mopidy-mpd 3.3.0 の mopidy_mpd/protocol/channels.py (client-to-client messaging
# section: subscribe/unsubscribe/channels/readmessages/sendmessage) は5コマンド
# 全て `raise MpdNotImplemented` のスタブ。rmpc本体 (mierak/rmpc) を実際にcloneして
# 調査したところ、CLIサブコマンド `rmpc sendmessage <channel> <text>`
# (rmpc/src/config/cli.rs Command::SendMessage、rmpc/src/core/command.rs で
# `client.send_message()` を実際に呼ぶ) が存在し、未実装のままだと ACK unimplemented に
# なる実害あるギャップ。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/MessageCommands.cxx, src/client/Subscribe.cxx,
# src/client/Message.cxx) のソースを確認して仕様を確定:
# - チャンネル名は `^[A-Za-z0-9:._-]+$` のみ許可 (subscribe/sendmessage は検証、
#   unsubscribe は実MPDもチャンネル名検証をせず存在確認のみ)
# - subscribe: 不正名 -> ACK_ERROR_ARG "invalid channel name"、
#   二重購読 -> ACK_ERROR_EXIST "already subscribed to this channel"
# - unsubscribe: 未購読チャンネル -> ACK_ERROR_NO_EXIST "not subscribed to this channel"
# - subscribe/unsubscribe は idle "subscription" イベントを発火
# - sendmessage: 不正名 -> ACK_ERROR_ARG、購読者0人 -> ACK_ERROR_NO_EXIST
#   "nobody is subscribed to this channel"、配送成功時は受信側に idle "message" イベント
# - channels: 全セッションの購読チャンネル名を重複排除して "channel: NAME" で列挙
# - readmessages: 自セッション宛の "channel:"/"message:" ペアを返し、読んだら消費 (pop)
#
# 実装: prio/crossfade/single-consume (mpdprio-patch.py 等) と同じ流儀で、
# translator.py にモジュールレベルの揮発性ストア (session id -> 購読チャンネル集合 /
# 未読メッセージ) を追加。idle "subscription" への通知は実 MPD の idle_add(IDLE_SUBSCRIPTION)
# 同様に全セッションへの無条件ブロードキャストが正しい仕様のため、actor.py の send_idle と
# 全く同じ機構 (`mopidy.listener.send(session.MpdSession, subsystem)`、pykka の `.tell()`
# 経由でスレッドセーフに全セッションへ配送) を再利用する。session.py の import サイクル
# (session -> dispatcher -> protocol.load_protocol_modules() -> channels.py) を避けるため、
# channels.py 側での session モジュール参照は関数内 (呼び出し時) の遅延importにする。
# 接続切断時に購読/メッセージが残り続けないよう、session.py に on_stop を追加して
# クリーンアップする (実 MPD の Client::UnsubscribeAll 相当)。
#
# 追記 (既存パッチを改良): 実 MPD は "message" idle イベントを「新規に購読者のメッセージ
# キューが空から非空になった、その購読者のみ」に個別配送する仕様だが、初版は
# mopidy.listener.send による全セッションブロードキャストを message にも流用しており
# 無関係なセッションを idle から余分に起こしていた (旧known constraint)。改良: subscribe
# 時に session の actor_ref (pykka Actor が自身で保持する ActorRef、context.session は
# 実体のアクターインスタンス自身なので同一スレッド内で同期的に取得可能) を
# translator._channel_actor_refs に保存し、sendmessage は channel_push_message() が返す
# 「実際に配送されたセッションの actor_ref 一覧」だけへ pykka.messages.ProxyCall を直接
# .tell() する _mpdchannels_notify_targeted() で個別通知するよう変更 (subscription は
# 従来通りブロードキャストのまま、message のみ実MPD仕様に合わせて個別配送化)。
# subsystems には bare `idle` (引数無し) でも拾えるよう status.py の SUBSYSTEMS に
# "subscription"/"message" を追加 (実 MPD の idle サブシステム一覧に合わせる)。

pp = "mopidy_mpd/protocol/channels.py"
s = open(pp).read()

MARKER = "_mpdchannels_name_re"
if MARKER in s:
    print("channels.py already patched, skip")
else:
    old = '''from mopidy_mpd import exceptions, protocol


@protocol.commands.add("subscribe")
def subscribe(context, channel):
    """
    *musicpd.org, client to client section:*

        ``subscribe {NAME}``

        Subscribe to a channel. The channel is created if it does not exist
        already. The name may consist of alphanumeric ASCII characters plus
        underscore, dash, dot and colon.
    """
    # TODO: match channel against [A-Za-z0-9:._-]+
    raise exceptions.MpdNotImplemented  # TODO


@protocol.commands.add("unsubscribe")
def unsubscribe(context, channel):
    """
    *musicpd.org, client to client section:*

        ``unsubscribe {NAME}``

        Unsubscribe from a channel.
    """
    # TODO: match channel against [A-Za-z0-9:._-]+
    raise exceptions.MpdNotImplemented  # TODO


@protocol.commands.add("channels")
def channels(context):
    """
    *musicpd.org, client to client section:*

        ``channels``

        Obtain a list of all channels. The response is a list of "channel:"
        lines.
    """
    raise exceptions.MpdNotImplemented  # TODO


@protocol.commands.add("readmessages")
def readmessages(context):
    """
    *musicpd.org, client to client section:*

        ``readmessages``

        Reads messages for this client. The response is a list of "channel:"
        and "message:" lines.
    """
    raise exceptions.MpdNotImplemented  # TODO


@protocol.commands.add("sendmessage")
def sendmessage(context, channel, text):
    """
    *musicpd.org, client to client section:*

        ``sendmessage {CHANNEL} {TEXT}``

        Send a message to the specified channel.
    """
    # TODO: match channel against [A-Za-z0-9:._-]+
    raise exceptions.MpdNotImplemented  # TODO
'''
    assert s.count(old) == 1, f"old count={s.count(old)}"

    new = '''import re

from mopidy_mpd import exceptions, protocol, translator

_mpdchannels_name_re = re.compile(r"^[A-Za-z0-9:._-]+$")


def _mpdchannels_notify(subsystem):
    # session.py への import サイクルを避けるため呼び出し時に遅延import する。
    from mopidy import listener
    from mopidy_mpd import session as mpd_session

    listener.send(mpd_session.MpdSession, subsystem)


def _mpdchannels_notify_targeted(actor_refs, subsystem):
    # 実 MPD は "message" idle イベントを購読者全員へブロードキャストせず、実際に
    # メッセージを受け取ったセッションだけへ個別配送する。mopidy.listener.send は
    # 対象クラスの全アクターへ無条件配送するため使えず、ここでは同じ
    # pykka.messages.ProxyCall による .tell() を、渡された actor_ref だけに絞って送る。
    from pykka.messages import ProxyCall

    for actor_ref in actor_refs:
        actor_ref.tell(ProxyCall(attr_path=["on_event"], args=[subsystem], kwargs={}))


@protocol.commands.add("subscribe")
def subscribe(context, channel):
    """
    *musicpd.org, client to client section:*

        ``subscribe {NAME}``

        Subscribe to a channel. The channel is created if it does not exist
        already. The name may consist of alphanumeric ASCII characters plus
        underscore, dash, dot and colon.
    """
    if not _mpdchannels_name_re.match(channel):
        raise exceptions.MpdArgError("invalid channel name")
    if not translator.channel_subscribe(
        id(context.session), channel, context.session.actor_ref
    ):
        raise exceptions.MpdExistError("already subscribed to this channel")
    _mpdchannels_notify("subscription")


@protocol.commands.add("unsubscribe")
def unsubscribe(context, channel):
    """
    *musicpd.org, client to client section:*

        ``unsubscribe {NAME}``

        Unsubscribe from a channel.
    """
    if not translator.channel_unsubscribe(id(context.session), channel):
        raise exceptions.MpdNoExistError("not subscribed to this channel")
    _mpdchannels_notify("subscription")


@protocol.commands.add("channels")
def channels(context):
    """
    *musicpd.org, client to client section:*

        ``channels``

        Obtain a list of all channels. The response is a list of "channel:"
        lines.
    """
    return [("channel", name) for name in translator.channel_list()]


@protocol.commands.add("readmessages")
def readmessages(context):
    """
    *musicpd.org, client to client section:*

        ``readmessages``

        Reads messages for this client. The response is a list of "channel:"
        and "message:" lines.
    """
    result = []
    for channel, text in translator.channel_read_messages(id(context.session)):
        result.append(("channel", channel))
        result.append(("message", text))
    return result


@protocol.commands.add("sendmessage")
def sendmessage(context, channel, text):
    """
    *musicpd.org, client to client section:*

        ``sendmessage {CHANNEL} {TEXT}``

        Send a message to the specified channel.
    """
    if not _mpdchannels_name_re.match(channel):
        raise exceptions.MpdArgError("invalid channel name")
    targets = translator.channel_push_message(channel, text)
    if not targets:
        raise exceptions.MpdNoExistError("nobody is subscribed to this channel")
    _mpdchannels_notify_targeted(targets, "message")
'''
    assert new != old
    s = s.replace(old, new, 1)
    open(pp, "w").write(s)
    print("patched channels.py: subscribe/unsubscribe/channels/readmessages/sendmessage を実装")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER2 = "_channel_subscriptions"
if MARKER2 in t:
    print("translator.py already patched, skip")
else:
    anchor = "logger = logging.getLogger(__name__)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "# channels.py (client-to-client messaging) 用の揮発性ストア。session id\n"
        "# (id(context.session)、接続毎に一意) をキーに購読チャンネル集合・未読メッセージ・\n"
        "# ActorRef を保持する。接続切断時は session.py の on_stop から channel_cleanup()\n"
        "# で破棄する。actor_ref は message idle イベントを購読者全員へブロードキャスト\n"
        "# せず実際の受信者だけへ個別配送するために使う (実 MPD の Client::PushMessage 相当)。\n"
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
        "\n"
    )
    t = t.replace(anchor, anchor + store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: channels 用の購読/メッセージ揮発性ストアを追加")

sp = "mopidy_mpd/session.py"
s3 = open(sp).read()

MARKER3 = "channel_cleanup"
if MARKER3 in s3:
    print("session.py already patched, skip")
else:
    old_import = "from mopidy_mpd import dispatcher, formatting, network, protocol\n"
    assert s3.count(old_import) == 1, f"old_import count={s3.count(old_import)}"
    new_import = "from mopidy_mpd import dispatcher, formatting, network, protocol, translator\n"
    s3 = s3.replace(old_import, new_import, 1)

    old_close = (
        "    def close(self):\n"
        "        self.stop()\n"
    )
    assert s3.count(old_close) == 1, f"old_close count={s3.count(old_close)}"
    new_close = (
        "    def on_stop(self):\n"
        "        # channels.py の client-to-client messaging 購読/未読メッセージを破棄\n"
        "        # (実 MPD の Client::UnsubscribeAll 相当)。\n"
        "        translator.channel_cleanup(id(self))\n"
        "        super().on_stop()\n"
        "\n"
        "    def close(self):\n"
        "        self.stop()\n"
    )
    s3 = s3.replace(old_close, new_close, 1)
    open(sp, "w").write(s3)
    print("patched session.py: on_stop で channel_cleanup を実行")

stp = "mopidy_mpd/protocol/status.py"
s4 = open(stp).read()

MARKER4 = '"subscription"'
if MARKER4 in s4:
    print("status.py already patched, skip")
else:
    old_subsystems = (
        "SUBSYSTEMS = [\n"
        '    "database",\n'
        '    "mixer",\n'
        '    "options",\n'
        '    "output",\n'
        '    "player",\n'
        '    "playlist",\n'
        '    "stored_playlist",\n'
        '    "update",\n'
        "]\n"
    )
    assert s4.count(old_subsystems) == 1, f"old_subsystems count={s4.count(old_subsystems)}"
    new_subsystems = (
        "SUBSYSTEMS = [\n"
        '    "database",\n'
        '    "message",\n'
        '    "mixer",\n'
        '    "options",\n'
        '    "output",\n'
        '    "player",\n'
        '    "playlist",\n'
        '    "stored_playlist",\n'
        '    "subscription",\n'
        '    "update",\n'
        "]\n"
    )
    s4 = s4.replace(old_subsystems, new_subsystems, 1)
    open(stp, "w").write(s4)
    print("patched status.py: SUBSYSTEMS に message/subscription を追加 (bare idle も拾う)")
