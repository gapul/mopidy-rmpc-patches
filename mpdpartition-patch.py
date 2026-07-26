# mopidy-mpd 3.3.0 は partition/listpartitions/newpartition/delpartition/moveoutput
# (partition commands section) をコマンド登録自体していない (mount.py のような
# スタブすら存在しない、送ると `ACK unknown command`)。rmpc本体 (mierak/rmpc) を
# 実際にcloneして調査したところ、rmpc-mpd/src/mpd_client.rs に
# send_switch_to_partition/send_new_partition/send_list_partitions/send_delete_partition/
# send_move_output が定義され、rmpc/src/ui/mod.rs のグローバルアクション
# `GlobalAction::Partition` (パーティション切替/新規作成メニュー、実際にキーバインド可能) と
# rmpc/src/ui/modals/outputs.rs (出力を別パーティションへ移動するメニュー) から実際に
# 呼び出されている、実害のあるギャップと判明。加えて `status` の `partition` フィールドも
# rmpc-mpd/src/commands/status.rs で常時パースされ (`ctx.status.partition`)、パーティション
# メニューの「デフォルトへ切替」表示判定に使われる。TODO 全項目消化済みのため自走エージェントが
# 調査して新規発見・追加した項目 (mpdmount-patch.py 等と同じ「rmpc が実際に送るがバックエンドが
# 未実装」パターン)。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/PartitionCommands.cxx) を実際にcloneして
# ソース確認し仕様を確定:
# - partition {NAME}: 名前の文字種チェックなし。存在しない -> ACK_ERROR_NO_EXIST
#   "partition does not exist"。
# - listpartitions: 全パーティションを "partition: NAME" で列挙。
# - newpartition {NAME}: 不正名 (英数字+`-`+`_`以外を含む、または空) ->
#   ACK_ERROR_ARG "bad name"、既に存在 -> ACK_ERROR_EXIST "name already exists"、
#   16個以上 (実MPDの暫定上限) -> ACK_ERROR_UNKNOWN "too many partitions"。
# - delpartition {NAME}: 不正名 -> ACK_ERROR_ARG "bad name"、存在しない ->
#   ACK_ERROR_NO_EXIST "no such partition"、default (常に先頭のパーティション) ->
#   ACK_ERROR_UNKNOWN "cannot delete the default partition"、接続中クライアントが
#   居る -> ACK_ERROR_UNKNOWN "partition still has clients"、出力が居る ->
#   ACK_ERROR_UNKNOWN "partition still has outputs"。成功時は idle "partition" を発火
#   (IDLE_PARTITION、src/protocol/IdleFlags.cxx で idle名は "partition" と確認)。
# - moveoutput {NAME}: 存在しない出力名 -> ACK_ERROR_NO_EXIST "No such output"。
#   既にクライアントの現パーティションに属していれば何もせず OK (idle無し)、
#   それ以外は所属パーティションを移動し idle "output" を発火 (IDLE_OUTPUT。
#   IDLE_PARTITION ではない点に注意、handle_moveoutput 内で EmitIdle(IDLE_OUTPUT) のみ)。
#
# 実装: mount/crossfade (mpdmount-patch.py/mpdcrossfade-patch.py) と同じ流儀で、
# パーティション一覧・出力の所属パーティションを translator.py にモジュールレベルの
# 揮発性ストアとして保持する (mopidy core 自体は複数パーティションでの独立再生や
# 複数出力を持たず、パッチ対象外のためプロトコル層の状態保持のみで妥当)。
# パーティションへの現在の割り当ては channels.py の購読と同じくセッション単位
# (id(context.session) をキー) で保持し、切断時は session.py の on_stop から
# 破棄する (mpdchannels-patch.py が追加した on_stop に partition_cleanup を追加)。
# idle 通知は mpdchannels-patch.py の _mpdchannels_notify と全く同じ機構
# (mopidy.listener.send(session.MpdSession, subsystem)) を再利用し、status.py の
# SUBSYSTEMS に "partition" を追加して bare `idle` でも拾えるようにする (audio_output.py
# の唯一の出力 "Mute" は既に SUBSYSTEMS に "output" があるため追加不要)。`status` の
# 応答にも `partition` フィールドを追加する (rmpc が status.partition を常時参照するため)。
#
# 既知の制約: mopidy core は audio_output.py が返す単一の仮想出力 ("Mute", outputid 0)
# しか持たず、moveoutput で別パーティションへ移した所属先で実際に音が鳴る/鳴らないという
# 実効果は無い (mount で登録したURIが実際にブラウズ可能になるわけではないのと同種の限界)。
# この実装はあくまでプロトコル層 (5コマンドの往復・エラー応答・idle通知・status.partition)
# の互換性のみを提供する。

pp = "mopidy_mpd/protocol/partition.py"

MARKER = "_mpdpartition_name_re"

import os

if os.path.exists(pp) and MARKER in open(pp).read():
    print("partition.py already patched, skip")
else:
    content = '''import re

from mopidy_mpd import exceptions, protocol, translator

_mpdpartition_name_re = re.compile(r"^[A-Za-z0-9_-]+$")


def _mpdpartition_notify(subsystem):
    # session.py への import サイクルを避けるため呼び出し時に遅延import する
    # (mpdchannels-patch.py の _mpdchannels_notify と同じ理由)。
    from mopidy import listener
    from mopidy_mpd import session as mpd_session

    listener.send(mpd_session.MpdSession, subsystem)


@protocol.commands.add("partition")
def partition(context, name):
    """
    *musicpd.org, partition commands section:*

        ``partition {NAME}``

        Switch the client to a different partition.
    """
    if not translator.partition_switch(id(context.session), name):
        raise exceptions.MpdNoExistError("partition does not exist")


@protocol.commands.add("listpartitions")
def listpartitions(context):
    """
    *musicpd.org, partition commands section:*

        ``listpartitions``

        Print a list of partitions.
    """
    return [("partition", name) for name in translator.partition_list()]


@protocol.commands.add("newpartition")
def newpartition(context, name):
    """
    *musicpd.org, partition commands section:*

        ``newpartition {NAME}``

        Create a new partition.
    """
    if not _mpdpartition_name_re.match(name):
        raise exceptions.MpdArgError("bad name")
    if len(translator.partition_list()) >= 16:
        raise exceptions.MpdUnknownError("too many partitions")
    if not translator.partition_create(name):
        raise exceptions.MpdExistError("name already exists")
    _mpdpartition_notify("partition")


@protocol.commands.add("delpartition")
def delpartition(context, name):
    """
    *musicpd.org, partition commands section:*

        ``delpartition {NAME}``

        Delete a partition. The partition must be empty (no connected
        clients and no outputs).
    """
    if not _mpdpartition_name_re.match(name):
        raise exceptions.MpdArgError("bad name")
    if not translator.partition_exists(name):
        raise exceptions.MpdNoExistError("no such partition")
    if name == translator.partition_list()[0]:
        raise exceptions.MpdUnknownError("cannot delete the default partition")
    if translator.partition_client_count(name) > 0:
        raise exceptions.MpdUnknownError("partition still has clients")
    if translator.partition_output_count(name) > 0:
        raise exceptions.MpdUnknownError("partition still has outputs")
    translator.partition_delete(name)
    _mpdpartition_notify("partition")


@protocol.commands.add("moveoutput")
def moveoutput(context, name):
    """
    *musicpd.org, partition commands section:*

        ``moveoutput {NAME}``

        Move an output to the current partition.
    """
    current = translator.output_partition_get(name)
    if current is None:
        raise exceptions.MpdNoExistError("No such output")
    dest = translator.partition_get(id(context.session))
    if current != dest:
        translator.output_partition_move(name, dest)
        _mpdpartition_notify("output")
'''
    open(pp, "w").write(content)
    print("created partition.py: partition/listpartitions/newpartition/delpartition/moveoutput を実装")

ip = "mopidy_mpd/protocol/__init__.py"
si = open(ip).read()

MARKERI = "        partition,\n"
if MARKERI in si:
    print("protocol/__init__.py already patched, skip")
else:
    old_imports = (
        "    from . import (  # noqa\n"
        "        audio_output,\n"
        "        channels,\n"
        "        command_list,\n"
        "        connection,\n"
        "        current_playlist,\n"
        "        mount,\n"
        "        music_db,\n"
        "        playback,\n"
        "        reflection,\n"
        "        status,\n"
        "        stickers,\n"
        "        stored_playlists,\n"
        "    )\n"
    )
    assert si.count(old_imports) == 1, f"old_imports count={si.count(old_imports)}"
    new_imports = (
        "    from . import (  # noqa\n"
        "        audio_output,\n"
        "        channels,\n"
        "        command_list,\n"
        "        connection,\n"
        "        current_playlist,\n"
        "        mount,\n"
        "        music_db,\n"
        "        partition,\n"
        "        playback,\n"
        "        reflection,\n"
        "        status,\n"
        "        stickers,\n"
        "        stored_playlists,\n"
        "    )\n"
    )
    si = si.replace(old_imports, new_imports, 1)
    open(ip, "w").write(si)
    print("patched protocol/__init__.py: load_protocol_modules に partition を追加")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER2 = "_partitions = "
if MARKER2 in t:
    print("translator.py already patched, skip")
else:
    anchor = "logger = logging.getLogger(__name__)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "# partition.py (partition/listpartitions/newpartition/delpartition/moveoutput)\n"
        "# 用の揮発性ストア。mopidy core は複数パーティションでの独立再生や複数出力を\n"
        "# 持たないため (パッチ対象外)、mount/crossfadeと同種にプロトコル層の状態保持の\n"
        "# みを提供する。\n"
        '_partitions = ["default"]  # 挿入順、先頭が実MPD同様のdefault (削除不可)\n'
        "_session_partition = {}  # session id -> partition名 (未登録はdefault扱い)\n"
        '_output_partition = {"Mute": "default"}  # audio_output.pyの唯一の出力の所属\n'
        "\n"
        "\n"
        "def partition_list():\n"
        "    return list(_partitions)\n"
        "\n"
        "\n"
        "def partition_exists(name):\n"
        "    return name in _partitions\n"
        "\n"
        "\n"
        "def partition_get(session_id):\n"
        '    return _session_partition.get(session_id, "default")\n'
        "\n"
        "\n"
        "def partition_switch(session_id, name):\n"
        "    if name not in _partitions:\n"
        "        return False\n"
        "    _session_partition[session_id] = name\n"
        "    return True\n"
        "\n"
        "\n"
        "def partition_create(name):\n"
        "    if name in _partitions:\n"
        "        return False\n"
        "    _partitions.append(name)\n"
        "    return True\n"
        "\n"
        "\n"
        "def partition_delete(name):\n"
        "    _partitions.remove(name)\n"
        "\n"
        "\n"
        "def partition_client_count(name):\n"
        "    return sum(1 for p in _session_partition.values() if p == name)\n"
        "\n"
        "\n"
        "def partition_output_count(name):\n"
        "    return sum(1 for p in _output_partition.values() if p == name)\n"
        "\n"
        "\n"
        "def partition_cleanup(session_id):\n"
        "    _session_partition.pop(session_id, None)\n"
        "\n"
        "\n"
        "def output_partition_get(name):\n"
        "    return _output_partition.get(name)\n"
        "\n"
        "\n"
        "def output_partition_move(name, dest):\n"
        "    _output_partition[name] = dest\n"
        "\n"
    )
    t = t.replace(anchor, anchor + store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: partition/output 所属の揮発性ストアを追加")

sp = "mopidy_mpd/session.py"
s3 = open(sp).read()

MARKER3 = "partition_cleanup"
if MARKER3 in s3:
    print("session.py already patched, skip")
else:
    old_close = (
        "    def on_stop(self):\n"
        "        # channels.py の client-to-client messaging 購読/未読メッセージを破棄\n"
        "        # (実 MPD の Client::UnsubscribeAll 相当)。\n"
        "        translator.channel_cleanup(id(self))\n"
        "        super().on_stop()\n"
    )
    assert s3.count(old_close) == 1, f"old_close count={s3.count(old_close)}"
    new_close = (
        "    def on_stop(self):\n"
        "        # channels.py の client-to-client messaging 購読/未読メッセージを破棄\n"
        "        # (実 MPD の Client::UnsubscribeAll 相当)。\n"
        "        translator.channel_cleanup(id(self))\n"
        "        # partition.py のパーティション割り当てを破棄 (実MPDの\n"
        "        # ~Client()時のパーティション離脱相当)。\n"
        "        translator.partition_cleanup(id(self))\n"
        "        super().on_stop()\n"
    )
    s3 = s3.replace(old_close, new_close, 1)
    open(sp, "w").write(s3)
    print("patched session.py: on_stop で partition_cleanup を実行")

stp = "mopidy_mpd/protocol/status.py"
s4 = open(stp).read()

MARKER4 = '"partition"'
if MARKER4 in s4:
    print("status.py SUBSYSTEMS already patched, skip")
else:
    old_subsystems = (
        "SUBSYSTEMS = [\n"
        '    "database",\n'
        '    "message",\n'
        '    "mixer",\n'
        '    "mount",\n'
        '    "options",\n'
        '    "output",\n'
        '    "player",\n'
        '    "playlist",\n'
        '    "stored_playlist",\n'
        '    "subscription",\n'
        '    "update",\n'
        "]\n"
    )
    assert s4.count(old_subsystems) == 1, f"old_subsystems count={s4.count(old_subsystems)}"
    new_subsystems = (
        "SUBSYSTEMS = [\n"
        '    "database",\n'
        '    "message",\n'
        '    "mixer",\n'
        '    "mount",\n'
        '    "options",\n'
        '    "output",\n'
        '    "partition",\n'
        '    "player",\n'
        '    "playlist",\n'
        '    "stored_playlist",\n'
        '    "subscription",\n'
        '    "update",\n'
        "]\n"
    )
    s4 = s4.replace(old_subsystems, new_subsystems, 1)
    open(stp, "w").write(s4)
    print("patched status.py: SUBSYSTEMS に partition を追加 (bare idle も拾う)")

MARKER5 = '("partition", translator.partition_get'
if MARKER5 in s4:
    print("status.py partition field already patched, skip")
else:
    old_result = (
        "    result = [\n"
        '        ("volume", _status_volume(futures)),\n'
    )
    assert s4.count(old_result) == 1, f"old_result count={s4.count(old_result)}"
    new_result = (
        "    result = [\n"
        '        ("partition", translator.partition_get(id(context.session))),\n'
        '        ("volume", _status_volume(futures)),\n'
    )
    s4 = s4.replace(old_result, new_result, 1)
    open(stp, "w").write(s4)
    print("patched status.py: status応答に partition フィールドを追加")
