# mopidy_mpd/protocol/partition.py の `delpartition {NAME}` ハンドラが、
# translator.partition_exists(name) (存在確認) / translator.partition_list()[0]
# (default判定) / translator.partition_client_count(name) (クライアント数確認)
# / translator.partition_output_count(name) (出力数確認) / translator.
# partition_delete(name) (削除実行) という5回の**別々**の translator.py 呼び出し
# で構成されている不具合。mpdpartitionrace-patch.py が個々の呼び出しに
# _partition_lock (threading.RLock) を掛けクラッシュ (dict/list走査中の
# RuntimeError) は解消済みだが、ハンドラ側の「4種のチェック→削除」という
# 複合操作全体はアトミックではないまま残っていた。TODO/既知の残課題を全項目
# 消化済みのため自走エージェントが再監査して発見した項目 (mpdmounttoctou-
# patch.py が mount.py 側の全く同型の複合チェックTOCTOUを mount_try_add() で
# 単一ロックスコープにまとめて対処済みなのに対し、partition.py の
# delpartition 側は未着手のまま残っていた)。
#
# 実害: `translator.partition_client_count(name) > 0` を確認した直後、
# `translator.partition_delete(name)` が実行されるまでの間に別クライアントが
# `partition {name}` (partition_switch、これも _partition_lock を取るが
# delpartition側とは別のロック取得区間) を実行してそのパーティションへ
# 切り替えると、「クライアント0人」を確認した時点の判定はもはや古く、実際には
# クライアントが存在する状態のまま `partition_delete` が削除を実行してしまう。
# 切り替えた側のセッションは `_session_partition` に存在しないパーティション名
# へ紐付いたまま残り (partition_cleanup は切断時のみ実行)、以後の `status` は
# 削除済みの `partition:` 名を返し続け、audio_output.py の出力所属判定とも
# 食い違ったままになる (実MPDが `delpartition` の前提とする
# 「空パーティションのみ削除可能」という不変条件が破れる)。
#
# 修正: mpdmounttoctou-patch.py の mount_try_add() と同じ流儀で、存在確認・
# default判定・クライアント数確認・出力数確認・削除を1つの translator.py 側
# 関数 partition_try_delete() にまとめ _partition_lock を1回だけ保持したまま
# 最後まで実行する。partition.py 側は名前の正規表現バリデーション (共有状態を
# 参照しない純粋なフォーマットチェックのためロック外のままでよい) の後に
# この1関数を呼び、返ってきた状態文字列に応じて元と同じACKメッセージ・
# 優先順位で例外を送出するだけにする。

import ast

TRANSLATOR = "mopidy_mpd/translator.py"
PARTITION = "mopidy_mpd/protocol/partition.py"

# --- translator.py: partition_try_delete() を追加 ---
s = open(TRANSLATOR).read()

MARKER = "def partition_try_delete("
if MARKER in s:
    print("mpdpartitiondeltoctou already applied to translator.py, skip")
else:
    OLD = (
        "def partition_delete(name):\n"
        "    with _partition_lock:\n"
        "        if name in _partitions:\n"
        "            _partitions.remove(name)\n"
        "\n"
        "\n"
        "def partition_client_count(name):\n"
    )
    assert s.count(OLD) == 1, f"OLD(translator) count={s.count(OLD)}"
    NEW = (
        "def partition_delete(name):\n"
        "    with _partition_lock:\n"
        "        if name in _partitions:\n"
        "            _partitions.remove(name)\n"
        "\n"
        "\n"
        "def partition_try_delete(name):\n"
        "    # delpartitionハンドラの存在確認+default判定+クライアント数確認+\n"
        "    # 出力数確認+削除を単一ロックで直列化するTOCTOU対策\n"
        "    # (mpdpartitiondeltoctou-patch.py)。個別に呼ぶと、クライアント数==0\n"
        "    # を確認した直後・削除実行前に別クライアントが partition switch で\n"
        "    # そのパーティションへ切り替えると、実際にはクライアントが存在する\n"
        "    # 状態のまま削除されてしまう (mpdmounttoctou-patch.pyのmount_try_add()\n"
        "    # と同型の対策)。\n"
        "    with _partition_lock:\n"
        '        if name not in _partitions:\n'
        '            return "not_found"\n'
        "        if name == _partitions[0]:\n"
        '            return "default"\n'
        "        if any(p == name for p in _session_partition.values()):\n"
        '            return "has_clients"\n'
        "        if any(p == name for p in _output_partition.values()):\n"
        '            return "has_outputs"\n'
        "        _partitions.remove(name)\n"
        "        return None\n"
        "\n"
        "\n"
        "def partition_client_count(name):\n"
    )
    s = s.replace(OLD, NEW, 1)
    open(TRANSLATOR, "w").write(s)
    ast.parse(s)
    print(
        "patched translator.py: partition_try_delete()を追加し、delpartitionの"
        "存在確認・default判定・クライアント数確認・出力数確認・削除を単一"
        "ロックスコープでアトミックに実行できるようにした"
    )

# --- partition.py: delpartition() ハンドラを partition_try_delete() 経由に変更 ---
s = open(PARTITION).read()

MARKER2 = "translator.partition_try_delete("
if MARKER2 in s:
    print("mpdpartitiondeltoctou already applied to partition.py, skip")
else:
    OLD2 = (
        "    if not translator.partition_exists(name):\n"
        '        raise exceptions.MpdNoExistError("no such partition")\n'
        "    if name == translator.partition_list()[0]:\n"
        '        raise exceptions.MpdUnknownError("cannot delete the default partition")\n'
        "    if translator.partition_client_count(name) > 0:\n"
        '        raise exceptions.MpdUnknownError("partition still has clients")\n'
        "    if translator.partition_output_count(name) > 0:\n"
        '        raise exceptions.MpdUnknownError("partition still has outputs")\n'
        "    translator.partition_delete(name)\n"
        '    _mpdpartition_notify("partition")\n'
    )
    assert s.count(OLD2) == 1, f"OLD2(partition.py) count={s.count(OLD2)}"
    NEW2 = (
        "    status = translator.partition_try_delete(name)\n"
        '    if status == "not_found":\n'
        '        raise exceptions.MpdNoExistError("no such partition")\n'
        '    if status == "default":\n'
        '        raise exceptions.MpdUnknownError("cannot delete the default partition")\n'
        '    if status == "has_clients":\n'
        '        raise exceptions.MpdUnknownError("partition still has clients")\n'
        '    if status == "has_outputs":\n'
        '        raise exceptions.MpdUnknownError("partition still has outputs")\n'
        '    _mpdpartition_notify("partition")\n'
    )
    s = s.replace(OLD2, NEW2, 1)
    open(PARTITION, "w").write(s)
    ast.parse(s)
    print(
        "patched partition.py: delpartition()ハンドラをpartition_try_delete()"
        "経由のアトミックなチェック+削除に変更し、クライアント数チェック直後に"
        "別接続がpartition switchで割り込んだ場合のサイレントなTOCTOU"
        "(空でないパーティションが削除されてしまう不具合)を修正"
    )
