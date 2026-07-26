# mopidy-mpd 3.3.0 の mopidy_mpd/protocol/mount.py (mounts and neighbors section) は
# mount/unmount/listmounts/listneighbors の4コマンド全て `raise MpdNotImplemented` の
# スタブ。rmpc本体 (mierak/rmpc) を実際にcloneして調査したところ、CLIサブコマンド
# `rmpc mount <name> <path>` / `rmpc unmount <name>` / `rmpc listmounts`
# (rmpc/src/config/cli.rs Command::Mount/Unmount/ListMounts、rmpc/src/core/command.rs
# で client.mount()/unmount()/list_mounts() を実際に呼び出す) が存在し、mpdchannels-patch.py
# のコメントで「sticker/mount/listmounts 等と同じ『rmpc CLIサブコマンドとして実在するが
# バックエンドが未実装』パターン」として名指しされていた新規ギャップ。TODO 全項目消化済みの
# ため自走エージェントが調査して新規発見・追加した項目 (listneighborsはrmpc側で送信箇所が
# 無いためスコープ外、未着手のまま)。
#
# 実 MPD (MusicPlayerDaemon/MPD src/command/StorageCommands.cxx handle_mount/
# handle_unmount/handle_listmounts) のソースを実際にcloneしてソース確認し仕様を確定:
# - mount: PATH が空 or "/" を含む -> ACK_ERROR_ARG "Bad mount point"
#   (実MPDはトップレベルマウントのみ許可)、PATH が既にマウント済み ->
#   ACK_ERROR_ARG "Mount point busy"、URI が既に別PATHにマウント済み ->
#   ACK_ERROR_ARG "This storage is already mounted"、ストレージURIのスキームが
#   認識できない -> ACK_ERROR_ARG "Unrecognized storage URI"。成功時は idle "mount"
#   イベントを発火 (IDLE_MOUNT)。
# - unmount: PATH が空 -> ACK_ERROR_ARG "Bad mount point"、マウントされていない PATH ->
#   ACK_ERROR_ARG "Not a mount point"。成功時は idle "mount" イベントを発火。
# - listmounts: 全マウントを "mount: PATH" / "storage: URI" のペアで列挙。
#
# 実装: prio/crossfade (mpdprio-patch.py/mpdcrossfade-patch.py) と同じ流儀で、
# マウントテーブル (path -> uri) を translator.py にモジュールレベルの揮発性ストアとして
# 保持する。mount は channels.py の購読と異なり session (接続) 単位ではなくサーバー全体で
# 共有される実MPDの仕様通り、session cleanup は不要。idle 通知は mpdchannels-patch.py の
# _mpdchannels_notify と全く同じ機構 (mopidy.listener.send(session.MpdSession, subsystem)、
# pykka の .tell() 経由でスレッドセーフに全セッションへブロードキャスト) を再利用し、
# status.py の SUBSYSTEMS に "mount" を追加して bare `idle` でも拾えるようにする。
#
# 既知の制約: mopidy core (mopidy/core) 自体は実 MPD の CompositeStorage/nfs://・smb://
# 等の任意ネットワークストレージを実行時にマウントする機構を持たず、mopidy core 自体は
# パッチ対象外のため、mount で登録した URI が実際にブラウズ可能なディレクトリとして
# 現れることはない (crossfade が実際の再生に影響しないのと同種の限界)。この実装は
# あくまでプロトコル層 (mount/unmount/listmounts の往復・エラー応答・idle通知) の
# 互換性のみを提供する。

pp = "mopidy_mpd/protocol/mount.py"
s = open(pp).read()

MARKER = "_mpdmount_notify"
if MARKER in s:
    print("mount.py already patched, skip")
else:
    old = '''from mopidy_mpd import exceptions, protocol


@protocol.commands.add("mount")
def mount(context, path, uri):
    """
    *musicpd.org, mounts and neighbors section:*

        ``mount {PATH} {URI}``

        Mount the specified remote storage URI at the given path. Example::

            mount foo nfs://192.168.1.4/export/mp3

    .. versionadded:: 0.19
        New in MPD protocol version 0.19
    """
    raise exceptions.MpdNotImplemented  # TODO


@protocol.commands.add("unmount")
def unmount(context, path):
    """
    *musicpd.org, mounts and neighbors section:*

        ``unmount {PATH}``

        Unmounts the specified path. Example::

            unmount foo

    .. versionadded:: 0.19
        New in MPD protocol version 0.19
    """
    raise exceptions.MpdNotImplemented  # TODO


@protocol.commands.add("listmounts")
def listmounts(context):
    """
    *musicpd.org, mounts and neighbors section:*

        ``listmounts``

        Queries a list of all mounts. By default, this contains just the
        configured music_directory. Example::

            listmounts
            mount:
            storage: /home/foo/music
            mount: foo
            storage: nfs://192.168.1.4/export/mp3
            OK

    .. versionadded:: 0.19
        New in MPD protocol version 0.19
    """
    raise exceptions.MpdNotImplemented  # TODO
'''
    assert s.count(old) == 1, f"old count={s.count(old)}"

    new = '''from mopidy_mpd import exceptions, protocol, translator


def _mpdmount_notify():
    # session.py への import サイクルを避けるため呼び出し時に遅延import する
    # (mpdchannels-patch.py の _mpdchannels_notify と同じ理由)。
    from mopidy import listener
    from mopidy_mpd import session as mpd_session

    listener.send(mpd_session.MpdSession, "mount")


@protocol.commands.add("mount")
def mount(context, path, uri):
    """
    *musicpd.org, mounts and neighbors section:*

        ``mount {PATH} {URI}``

        Mount the specified remote storage URI at the given path. Example::

            mount foo nfs://192.168.1.4/export/mp3

    .. versionadded:: 0.19
        New in MPD protocol version 0.19
    """
    if not path or "/" in path:
        raise exceptions.MpdArgError("Bad mount point")
    if translator.mount_path_used(path):
        raise exceptions.MpdArgError("Mount point busy")
    if "://" not in uri:
        raise exceptions.MpdArgError("Unrecognized storage URI")
    if translator.mount_uri_used(uri):
        raise exceptions.MpdArgError("This storage is already mounted")
    translator.mount_add(path, uri)
    _mpdmount_notify()


@protocol.commands.add("unmount")
def unmount(context, path):
    """
    *musicpd.org, mounts and neighbors section:*

        ``unmount {PATH}``

        Unmounts the specified path. Example::

            unmount foo

    .. versionadded:: 0.19
        New in MPD protocol version 0.19
    """
    if not path:
        raise exceptions.MpdArgError("Bad mount point")
    if not translator.mount_remove(path):
        raise exceptions.MpdArgError("Not a mount point")
    _mpdmount_notify()


@protocol.commands.add("listmounts")
def listmounts(context):
    """
    *musicpd.org, mounts and neighbors section:*

        ``listmounts``

        Queries a list of all mounts. By default, this contains just the
        configured music_directory. Example::

            listmounts
            mount:
            storage: /home/foo/music
            mount: foo
            storage: nfs://192.168.1.4/export/mp3
            OK

    .. versionadded:: 0.19
        New in MPD protocol version 0.19
    """
    result = []
    for path, uri in translator.mount_list():
        result.append(("mount", path))
        result.append(("storage", uri))
    return result
'''
    assert new != old
    s = s.replace(old, new, 1)
    open(pp, "w").write(s)
    print("patched mount.py: mount/unmount/listmounts を実装")

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER2 = "_mounts = {}"
if MARKER2 in t:
    print("translator.py already patched, skip")
else:
    anchor = "logger = logging.getLogger(__name__)\n"
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    store = (
        "\n"
        "# mount.py (mount/unmount/listmounts) 用の揮発性ストア (path -> uri)。\n"
        "# 実 MPD のマウントテーブルと異なりプロセス再起動で消えるが、mopidy core自体は\n"
        "# ランタイムでの任意ストレージマウントに対応していないため (パッチ対象外)、\n"
        "# プロトコル層の状態保持のみで妥当。channels.pyの購読と違いセッション単位では\n"
        "# なくサーバー全体で共有 (実MPD仕様通り)。\n"
        "_mounts = {}\n"
        "\n"
        "\n"
        "def mount_add(path, uri):\n"
        "    _mounts[path] = uri\n"
        "\n"
        "\n"
        "def mount_remove(path):\n"
        "    return _mounts.pop(path, None) is not None\n"
        "\n"
        "\n"
        "def mount_path_used(path):\n"
        "    return path in _mounts\n"
        "\n"
        "\n"
        "def mount_uri_used(uri):\n"
        "    return uri in _mounts.values()\n"
        "\n"
        "\n"
        "def mount_list():\n"
        "    return sorted(_mounts.items())\n"
        "\n"
    )
    t = t.replace(anchor, anchor + store, 1)
    open(tp, "w").write(t)
    print("patched translator.py: mount テーブルの揮発性ストアを追加")

stp = "mopidy_mpd/protocol/status.py"
s2 = open(stp).read()

MARKER3 = '"mount",\n    "options"'
if MARKER3 in s2:
    print("status.py already patched, skip")
else:
    old_subsystems = (
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
    assert s2.count(old_subsystems) == 1, f"old_subsystems count={s2.count(old_subsystems)}"
    new_subsystems = (
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
    s2 = s2.replace(old_subsystems, new_subsystems, 1)
    open(stp, "w").write(s2)
    print("patched status.py: SUBSYSTEMS に mount を追加 (bare idle も拾う)")
