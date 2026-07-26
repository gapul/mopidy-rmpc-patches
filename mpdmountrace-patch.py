# mopidy_mpd/translator.py の mount.py (mount/unmount/listmounts) 用揮発性ストア
# _mounts (mpdmount-patch.py が追加、path -> uri) が、mpdurimaprace-patch.py /
# mpdchannelrace-patch.py / mpdpartitionrace-patch.py で修正した MpdUriMapper /
# channels.py / partition.py の各ストアと全く同じ理由でスレッド安全性を欠いていた
# 不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが再調査して発見した。
#
# 実害 (RuntimeError): `mount_uri_used(uri)` は `uri in _mounts.values()`、
# `mount_list()` は `sorted(_mounts.items())` と、いずれも _mounts の内容をその場で
# 走査する。一方 `mount_add(path, uri)` は `_mounts[path] = uri` で dict に新規キーを
# 追加しうる (`__setitem__`)。mount.py の `_mounts` は channels.py の購読や
# partition.py のセッション別ストアと異なり session (接続) 単位ではなくサーバー全体で
# 共有される (実MPD仕様通り、mpdmount-patch.py のコメントに明記) ため、mopidy_mpd が
# クライアント接続ごとに別スレッドの MpdSession アクターを立てる構成では、あるクライアントが
# `mount foo nfs://...` を実行し `_mounts` に新規キーを追加している最中に、**別の**
# クライアントが同時に `mount bar smb://...` (内部で `mount_uri_used()` が
# `_mounts.values()` を走査して重複URIチェック) や `listmounts`
# (`mount_list()` が `_mounts.items()` を走査) を実行すると、CPython の dict は
# 走査中に要素数が変化すると `RuntimeError: dictionary changed size during
# iteration` を送出する。`RuntimeError` は `exceptions.MpdAckError` のサブクラスでは
# ないため `dispatcher.py` の `_catch_mpd_ack_errors_filter` に捕捉されず、
# `session.py` にも保護が無いため pykka アクターの外まで伝播し
# `network.LineProtocol.on_failure` に到達、ACK エラーが一切返らずその接続の
# TCP セッションが問答無用で切断される (mount操作を一切していない接続が
# `listmounts` を叩いただけでも巻き込まれる)。
#
# 修正: mpdurimaprace-patch.py / mpdchannelrace-patch.py / mpdpartitionrace-patch.py
# と同じ流儀で、translator.py にモジュールレベルの `threading.RLock()`
# (`_mount_lock`) を追加し、mount_add/mount_remove/mount_path_used/mount_uri_used/
# mount_list の本体を `with _mount_lock:` で直列化する
# (いずれもローカルの dict 操作のみでバックエンドへのネットワーク呼び出しを
# 含まないため長時間ブロックの懸念は無い)。mount には partition.py の
# delpartition のような TOCTOU 二段構成 (exists確認→delete) は無く
# (mount.py 側は `translator.mount_remove(path)` の戻り値のみで
# 成否判定する単発呼び出し)、ValueError 系の実害は無い。

p = "mopidy_mpd/translator.py"
s = open(p).read()

MARKER = "_mount_lock"
if MARKER in s:
    print("mpdmountrace already applied to translator.py, skip")
else:
    old = (
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
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "_mounts = {}\n"
        "# 全クライアント接続(各々別スレッドのMpdSessionアクター)が上記のdictを共有\n"
        "# するため、読み書きはRLockで直列化する(mpdmountrace-patch.py)。\n"
        "_mount_lock = threading.RLock()\n"
        "\n"
        "\n"
        "def mount_add(path, uri):\n"
        "    with _mount_lock:\n"
        "        _mounts[path] = uri\n"
        "\n"
        "\n"
        "def mount_remove(path):\n"
        "    with _mount_lock:\n"
        "        return _mounts.pop(path, None) is not None\n"
        "\n"
        "\n"
        "def mount_path_used(path):\n"
        "    with _mount_lock:\n"
        "        return path in _mounts\n"
        "\n"
        "\n"
        "def mount_uri_used(uri):\n"
        "    with _mount_lock:\n"
        "        return uri in _mounts.values()\n"
        "\n"
        "\n"
        "def mount_list():\n"
        "    with _mount_lock:\n"
        "        return sorted(_mounts.items())\n"
    )
    s = s.replace(old, new, 1)

    # import threading: 既存の *race-patch.py のいずれかが既に追加済みのはずなので、
    # 未適用 (適用順が入れ替わった場合) にだけ念のため追加する。
    if "import threading" not in s:
        import_anchor = "import re\nimport time\n"
        assert s.count(import_anchor) == 1, f"import_anchor count={s.count(import_anchor)}"
        s = s.replace(import_anchor, "import re\nimport threading\nimport time\n", 1)

    open(p, "w").write(s)
    print(
        "patched translator.py: mount.py用のmount揮発性ストア(_mounts)が全クライアント"
        "接続間でロック無しに共有され、mount/listmounts実行中に別接続が同時にmount/"
        "listmountsするとdict走査中の変更でRuntimeErrorが発生し無関係な接続まで切断"
        "されてしまう不具合を修正 (threading.RLockでdict操作を直列化、"
        "mpdurimaprace-patch.py/mpdchannelrace-patch.py/mpdpartitionrace-patch.pyと"
        "同じ流儀)"
    )
