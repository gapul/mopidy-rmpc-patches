# mopidy_mpd/translator.py の partition.py (partition/listpartitions/newpartition/
# delpartition/moveoutput) 用揮発性ストア _partitions/_session_partition/
# _output_partition (mpdpartition-patch.py が追加) が、mpdurimaprace-patch.py /
# mpdchannelrace-patch.py で修正した MpdUriMapper / channels.py ストアと全く同じ
# 理由でスレッド安全性を欠いていた不具合。TODO/既知の残課題を全項目消化済みのため
# 自走エージェントが再調査して発見した。
#
# 実害1 (RuntimeError): `partition_client_count()`/`partition_output_count()` は
#   sum(1 for p in _session_partition.values() if p == name)
#   sum(1 for p in _output_partition.values() if p == name)
# という dict の内容をその場で走査するループを持つ (delpartition ハンドラが
# 「パーティションが空か」を確認するために呼ぶ)。一方 `partition_cleanup()` は
# 接続切断のたび (session.py の on_stop から partition 未使用のクライアントも
# 含め**無条件**に、mpdchannelrace-patch.py が修正した channel_cleanup と全く
# 同じ呼び出しパターンで) `_session_partition.pop(session_id, None)` する。
# CPython の dict は走査中に要素数が変化すると `RuntimeError: dictionary changed
# size during iteration` を送出するため、あるクライアントが `delpartition` 実行中に
# **別の**クライアントが切断する (partition機能を一切使っていない接続でもよい、
# ごくありふれた操作) と走査側で `RuntimeError` が飛ぶ。`RuntimeError` は
# `exceptions.MpdAckError` のサブクラスではないため `dispatcher.py` の
# `_catch_mpd_ack_errors_filter` に捕捉されず、`session.py` にも保護が無いため
# pykka アクターの外まで伝播し `network.LineProtocol.on_failure` に到達、ACK
# エラーが一切返らずその接続の TCP セッションが問答無用で切断される。同様に
# `output_partition_move()` による `_output_partition` への書き込みと
# `partition_output_count()` の走査が競合しても同じ `RuntimeError` になる。
#
# 実害2 (ValueError、TOCTOU): `delpartition` ハンドラは `partition.py` 側で
# `translator.partition_exists(name)` を確認した**後**に `translator.partition_delete(name)`
# (= `_partitions.remove(name)`) を呼ぶ2段構成のため、同名パーティションに対する
# `delpartition` を2接続が同時実行すると、両方が exists チェックを通過した後
# 片方が先に `remove()` して名前が消え、もう片方の `remove()` が
# `ValueError: list.remove(x): x not in list` を送出する (これも MpdAckError
# サブクラスではなくセッション切断に至る)。
#
# 修正: mpdurimaprace-patch.py / mpdchannelrace-patch.py と同じ流儀で、translator.py に
# モジュールレベルの `threading.RLock()` (`_partition_lock`) を追加し、
# partition_list/partition_exists/partition_get/partition_switch/partition_create/
# partition_delete/partition_client_count/partition_output_count/partition_cleanup/
# output_partition_get/output_partition_move の本体を `with _partition_lock:` で
# 直列化する (いずれもローカルの list/dict 操作のみでバックエンドへのネットワーク
# 呼び出しを含まないため長時間ブロックの懸念は無い)。実害2については
# `partition_delete()` 自体を `if name in _partitions: _partitions.remove(name)`
# という削除済みなら無害に no-op する実装へ変更し (mount_remove 等の既存の
# 「無ければ何もしない」流儀に合わせる)、2度目の delpartition がクラッシュせず
# 単に OK を返す (既に削除済みという結果自体は変わらない) ようにした。

p = "mopidy_mpd/translator.py"
s = open(p).read()

MARKER = "_partition_lock"
if MARKER in s:
    print("mpdpartitionrace already applied to translator.py, skip")
else:
    old = (
        "_partitions = [\"default\"]  # 挿入順、先頭が実MPD同様のdefault (削除不可)\n"
        "_session_partition = {}  # session id -> partition名 (未登録はdefault扱い)\n"
        "_output_partition = {\"Mute\": \"default\"}  # audio_output.pyの唯一の出力の所属\n"
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
        "    return _session_partition.get(session_id, \"default\")\n"
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
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "_partitions = [\"default\"]  # 挿入順、先頭が実MPD同様のdefault (削除不可)\n"
        "_session_partition = {}  # session id -> partition名 (未登録はdefault扱い)\n"
        "_output_partition = {\"Mute\": \"default\"}  # audio_output.pyの唯一の出力の所属\n"
        "# 全クライアント接続(各々別スレッドのMpdSessionアクター)が上記のlist/dictを\n"
        "# 共有するため、読み書きはRLockで直列化する(mpdpartitionrace-patch.py)。\n"
        "_partition_lock = threading.RLock()\n"
        "\n"
        "\n"
        "def partition_list():\n"
        "    with _partition_lock:\n"
        "        return list(_partitions)\n"
        "\n"
        "\n"
        "def partition_exists(name):\n"
        "    with _partition_lock:\n"
        "        return name in _partitions\n"
        "\n"
        "\n"
        "def partition_get(session_id):\n"
        "    with _partition_lock:\n"
        "        return _session_partition.get(session_id, \"default\")\n"
        "\n"
        "\n"
        "def partition_switch(session_id, name):\n"
        "    with _partition_lock:\n"
        "        if name not in _partitions:\n"
        "            return False\n"
        "        _session_partition[session_id] = name\n"
        "        return True\n"
        "\n"
        "\n"
        "def partition_create(name):\n"
        "    with _partition_lock:\n"
        "        if name in _partitions:\n"
        "            return False\n"
        "        _partitions.append(name)\n"
        "        return True\n"
        "\n"
        "\n"
        "def partition_delete(name):\n"
        "    with _partition_lock:\n"
        "        if name in _partitions:\n"
        "            _partitions.remove(name)\n"
        "\n"
        "\n"
        "def partition_client_count(name):\n"
        "    with _partition_lock:\n"
        "        return sum(1 for p in _session_partition.values() if p == name)\n"
        "\n"
        "\n"
        "def partition_output_count(name):\n"
        "    with _partition_lock:\n"
        "        return sum(1 for p in _output_partition.values() if p == name)\n"
        "\n"
        "\n"
        "def partition_cleanup(session_id):\n"
        "    with _partition_lock:\n"
        "        _session_partition.pop(session_id, None)\n"
        "\n"
        "\n"
        "def output_partition_get(name):\n"
        "    with _partition_lock:\n"
        "        return _output_partition.get(name)\n"
        "\n"
        "\n"
        "def output_partition_move(name, dest):\n"
        "    with _partition_lock:\n"
        "        _output_partition[name] = dest\n"
    )
    s = s.replace(old, new, 1)

    # import threading: mpdchannelrace-patch.py が既に追加済みのはずなので、
    # 未適用 (適用順が入れ替わった場合) にだけ念のため追加する。
    if "import threading" not in s:
        import_anchor = "import re\nimport time\n"
        assert s.count(import_anchor) == 1, f"import_anchor count={s.count(import_anchor)}"
        s = s.replace(import_anchor, "import re\nimport threading\nimport time\n", 1)

    open(p, "w").write(s)
    print(
        "patched translator.py: partition.py用のpartition/session/output揮発性ストアが"
        "全クライアント接続間でロック無しに共有され、delpartition実行中に別クライアントが"
        "切断するとdict走査中の変更でRuntimeErrorが発生し無関係な接続まで切断されて"
        "しまう不具合、および同名delpartitionの同時実行がValueErrorで切断される不具合を"
        "修正 (threading.RLockでlist/dict操作を直列化、mpdurimaprace-patch.py/"
        "mpdchannelrace-patch.pyと同じ流儀。partition_deleteはmount_remove同様の"
        "no-op化で二重削除を無害化)"
    )
