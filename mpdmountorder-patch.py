# mpdmounttoctou-patch.py が `mount {PATH} {URI}` のbusy/URI重複チェックを
# translator.mount_try_add() 1関数にまとめてアトミックにした際、そのすぐ手前で
# mount.py 側が単独で行っていた「URIスキーム認識チェック (`"://" in uri`)」を
# busyチェックより**先**に呼ぶ順序に変えてしまっていた不具合。
# (同patch自身のコメントは「参照しない純粋なバリデーションのため元のエラー文言・
# 優先順位を保った」と主張しているが、実際にはmpdmount-patch.py時点の元の並び
# ("bad mount point" -> busy -> "://"チェック -> uri_used) からURIスキーム
# チェックだけがbusyチェックより前に移動しており、優先順位は保たれていなかった。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが再監査して発見した項目。
#
# 実MPD (MusicPlayerDaemon/MPD src/command/StorageCommands.cxx handle_mount、
# raw curlで確認) のチェック順序: PATH空/"/"混入 -> "Bad mount point"、
# `composite.IsMountPoint(local_uri)` -> "Mount point busy"、
# `composite.IsMounted(remote_uri)` -> "This storage is already mounted"、
# `CreateStorageURI(remote_uri)` (スキーム認識) -> "Unrecognized storage URI"
# の順(busy/already-mountedが先、URIスキーム認識は最後)。
#
# 実害: 既に別スキームで使用中のmount pointに対し、スキーム無しURIで再mountを
# 試みると (`mount "foo" "no-scheme"` に対し "foo" が既にmount済み)、実MPDは
# "Mount point busy" を返すが、現行実装は "Unrecognized storage URI" を返して
# しまう(busyチェックに到達する前にURIスキームチェックで弾かれるため)。同様に
# 既に別名で同一URIがmount済みの状態で不正スキームURIを別名でmountしようと
# すると、実MPDの"This storage is already mounted"ではなく
# "Unrecognized storage URI"が返る。
#
# 修正: mount_try_add(path, uri) に「URIスキームが認識可能か」を第3引数
# recognized として渡し、単一ロックスコープ内で busy -> uri_used ->
# unrecognized の順に判定してから_mountsへ書き込む(TOCTOU安全性はそのまま
# 維持、優先順位だけ実MPDに合わせる)。mount.py側は"://"の有無を判定して
# mount_try_add()に渡すだけにし、判定結果(busy/uri_used/unrecognized/None)
# だけで分岐する。

import ast

TRANSLATOR = "mopidy_mpd/translator.py"
MOUNT = "mopidy_mpd/protocol/mount.py"

# --- translator.py: mount_try_add() に recognized 引数を追加 ---
s = open(TRANSLATOR).read()

OLD = (
    "def mount_try_add(path, uri):\n"
    "    # mount()ハンドラの busyチェック+URI重複チェック+追加を単一ロックで\n"
    "    # 直列化するTOCTOU対策 (mpdmounttoctou-patch.py)。個別に呼ぶと2接続が\n"
    "    # 同時にmountした場合、両方がチェックを通過してから片方のみが有効な\n"
    "    # 追加として残ってしまう (実MPDが保証するmount point/storage URIの\n"
    "    # 一意性が破れる)。\n"
    "    with _mount_lock:\n"
    '        if path in _mounts:\n'
    '            return "busy"\n'
    "        if uri in _mounts.values():\n"
    '            return "uri_used"\n'
    "        _mounts[path] = uri\n"
    "        return None\n"
)

if OLD not in s:
    print("mpdmountorder already applied to translator.py, skip")
else:
    NEW = (
        "def mount_try_add(path, uri, recognized):\n"
        "    # mount()ハンドラの busyチェック+URI重複チェック+スキーム認識チェック+\n"
        "    # 追加を単一ロックで直列化するTOCTOU対策 (mpdmounttoctou-patch.py)。\n"
        "    # 個別に呼ぶと2接続が同時にmountした場合、両方がチェックを通過して\n"
        "    # から片方のみが有効な追加として残ってしまう (実MPDが保証する\n"
        "    # mount point/storage URIの一意性が破れる)。busy/uri_used/\n"
        "    # unrecognizedの優先順位は実MPD (StorageCommands.cxx handle_mount:\n"
        "    # IsMountPoint -> IsMounted -> CreateStorageURI の順) に合わせる\n"
        "    # (mpdmountorder-patch.py)。\n"
        "    with _mount_lock:\n"
        '        if path in _mounts:\n'
        '            return "busy"\n'
        "        if uri in _mounts.values():\n"
        '            return "uri_used"\n'
        "        if not recognized:\n"
        '            return "unrecognized"\n'
        "        _mounts[path] = uri\n"
        "        return None\n"
    )
    assert s.count(OLD) == 1, f"OLD(translator) count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(TRANSLATOR, "w").write(s)
    ast.parse(s)
    print(
        "patched translator.py: mount_try_add()にrecognized引数を追加し、"
        "busy/uri_used/unrecognizedの優先順位を実MPDのbusy->already-mounted->"
        "unrecognizedの順に修正"
    )

# --- mount.py: URIスキームチェックをmount_try_add()経由に変更 ---
s = open(MOUNT).read()

OLD2 = (
    "    if not path or \"/\" in path:\n"
    "        raise exceptions.MpdArgError(\"Bad mount point\")\n"
    "    if \"://\" not in uri:\n"
    "        raise exceptions.MpdArgError(\"Unrecognized storage URI\")\n"
    "    status = translator.mount_try_add(path, uri)\n"
    '    if status == "busy":\n'
    "        raise exceptions.MpdArgError(\"Mount point busy\")\n"
    '    if status == "uri_used":\n'
    "        raise exceptions.MpdArgError(\"This storage is already mounted\")\n"
    "    _mpdmount_notify()\n"
)

if OLD2 not in s:
    print("mpdmountorder already applied to mount.py, skip")
else:
    NEW2 = (
        "    if not path or \"/\" in path:\n"
        "        raise exceptions.MpdArgError(\"Bad mount point\")\n"
        '    status = translator.mount_try_add(path, uri, "://" in uri)\n'
        '    if status == "busy":\n'
        "        raise exceptions.MpdArgError(\"Mount point busy\")\n"
        '    if status == "uri_used":\n'
        "        raise exceptions.MpdArgError(\"This storage is already mounted\")\n"
        '    if status == "unrecognized":\n'
        "        raise exceptions.MpdArgError(\"Unrecognized storage URI\")\n"
        "    _mpdmount_notify()\n"
    )
    assert s.count(OLD2) == 1, f"OLD2(mount.py) count={s.count(OLD2)}"
    s = s.replace(OLD2, NEW2, 1)
    open(MOUNT, "w").write(s)
    ast.parse(s)
    print(
        "patched mount.py: mount()ハンドラのURIスキーム認識チェックを"
        "mount_try_add()経由に変更し、busy/uri_usedチェックより後(実MPDの"
        "IsMountPoint->IsMounted->CreateStorageURIの順)に実行されるよう修正"
    )
