# mopidy_mpd/protocol/mount.py の `mount {PATH} {URI}` ハンドラが、
# translator.mount_path_used(path) (busyチェック) / translator.mount_uri_used(uri)
# (URI重複チェック) / translator.mount_add(path, uri) (追加) という3回の**別々**の
# translator.py呼び出しで構成されている不具合。mpdmountrace-patch.pyが各呼び出し
# 個別に _mount_lock (threading.RLock) を掛けクラッシュ (dict走査中のRuntimeError)
# は解消済みだが、ハンドラ側の「チェック3連続→追加」という複合操作全体は
# アトミックではないまま残っていた。TODO/既知の残課題を全項目消化済みのため
# 自走エージェントが再監査して発見した項目 (mpdpartitionrace-patch.py が
# delpartition の同種TOCTOUをexists確認→delete の2段構成として一部指摘・対処
# 済みなのに対し、mount.py 側は未着手のまま残っていた)。
#
# 実害: mount.py の _mounts は channels.py の購読 (session単位) や partition.py の
# セッション別ストアと異なり、実MPD仕様通りサーバー全体で共有される
# (mpdmount-patch.py のコメントに明記)。mopidy_mpd はクライアント接続ごとに別
# スレッドの MpdSession アクターを立てる構成のため、2接続が異なるURIで同じ
# mount pointを狙い `mount foo nfs://host-a/x` / `mount foo smb://host-b/y` を
# ほぼ同時に実行すると、両方が (別々にロックを取る) `mount_path_used("foo")` を
# 順に呼んだ時点ではまだどちらも `_mounts` に書き込んでいないため両方とも
# False (busy でない) を観測でき、両方とも "Mount point busy" を通過して
# 両方とも最終的に `translator.mount_add("foo", uri)` を実行してしまう。
# 後勝ちで片方の URI が黙って上書きされ、先に `mount` した側は
# "OK" を受け取ったにもかかわらず `listmounts` では自分が指定した URI が
# 消えている (実MPDが保証する「mount pointの排他性」が破れ、クライアントに
# 気付かれないまま異なるストレージがマウントされる)。同じ理由で
# mount_uri_used(uri) (「同一URIの二重マウント禁止」チェック) も
# 複合操作の外にあるため同時実行下では効果が保証されない。
#
# 修正: mpdplaylistcreateguard-patch.py 等と同様、チェックと書き込みを1つの
# translator.py 側関数にまとめ _mount_lock を1回だけ保持したまま最後まで
# 実行する (mpdurimaprace-patch.py/mpdpartitionrace-patch.py が確立した
# 「複合状態操作は単一ロックスコープでアトミックに」という流儀)。
# translator.mount_try_add(path, uri) を新設し、path busy / uri already
# mounted / 成功の3状態を返す。mount.py 側は path/uri の静的フォーマット
# 検証 (path の空文字・"/" 混入、uri の "://" 有無。いずれも共有状態を
# 参照しない純粋なバリデーションのため元のエラー文言・優先順位を保った
# ままロック外で先に行って問題ない) の後にこの1関数を呼ぶだけにする。

import ast

TRANSLATOR = "mopidy_mpd/translator.py"
MOUNT = "mopidy_mpd/protocol/mount.py"

# --- translator.py: mount_try_add() を追加 ---
s = open(TRANSLATOR).read()

MARKER = "def mount_try_add("
if MARKER in s:
    print("mpdmounttoctou already applied to translator.py, skip")
else:
    OLD = (
        "def mount_add(path, uri):\n"
        "    with _mount_lock:\n"
        "        _mounts[path] = uri\n"
        "\n"
        "\n"
        "def mount_remove(path):\n"
    )
    assert s.count(OLD) == 1, f"OLD(translator) count={s.count(OLD)}"
    NEW = (
        "def mount_add(path, uri):\n"
        "    with _mount_lock:\n"
        "        _mounts[path] = uri\n"
        "\n"
        "\n"
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
        "\n"
        "\n"
        "def mount_remove(path):\n"
    )
    s = s.replace(OLD, NEW, 1)
    open(TRANSLATOR, "w").write(s)
    ast.parse(s)
    print(
        "patched translator.py: mount_try_add()を追加し、mount pointの空き"
        "チェック・URI重複チェック・追加を単一ロックスコープでアトミックに実行"
        "できるようにした"
    )

# --- mount.py: mount() ハンドラを mount_try_add() 経由に変更 ---
s = open(MOUNT).read()

MARKER2 = "translator.mount_try_add("
if MARKER2 in s:
    print("mpdmounttoctou already applied to mount.py, skip")
else:
    OLD2 = (
        "    if not path or \"/\" in path:\n"
        "        raise exceptions.MpdArgError(\"Bad mount point\")\n"
        "    if translator.mount_path_used(path):\n"
        "        raise exceptions.MpdArgError(\"Mount point busy\")\n"
        "    if \"://\" not in uri:\n"
        "        raise exceptions.MpdArgError(\"Unrecognized storage URI\")\n"
        "    if translator.mount_uri_used(uri):\n"
        "        raise exceptions.MpdArgError(\"This storage is already mounted\")\n"
        "    translator.mount_add(path, uri)\n"
        "    _mpdmount_notify()\n"
    )
    assert s.count(OLD2) == 1, f"OLD2(mount.py) count={s.count(OLD2)}"
    NEW2 = (
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
    s = s.replace(OLD2, NEW2, 1)
    open(MOUNT, "w").write(s)
    ast.parse(s)
    print(
        "patched mount.py: mount()ハンドラをmount_try_add()経由のアトミックな"
        "チェック+追加に変更し、2接続が同じmount pointを同時に狙った場合の"
        "サイレントな上書き(TOCTOU)を修正"
    )
