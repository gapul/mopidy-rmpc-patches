# mopidy_mpd/protocol/partition.py の `moveoutput {NAME}` ハンドラが、
# translator.output_partition_get(name) (現在の所属確認) / translator.
# partition_get(id(context.session)) (移動先確認) / translator.
# output_partition_move(name, dest) (移動実行) という3回の**別々**の
# translator.py 呼び出しで構成されている不具合。個々の呼び出しは
# mpdpartitionrace-patch.py の _partition_lock (threading.RLock) で保護済み
# だが、「現在の所属を読む→移動先と比較→違えば書き込む」という複合操作
# 全体はアトミックではないまま残っていた。TODO/既知の残課題を全項目消化済み
# のため自走エージェントが再監査して発見した項目 (mount.py の mount
# ハンドラを mount_try_add() で、partition.py の delpartition/newpartition を
# partition_try_delete()/partition_try_create() でそれぞれ単一ロックスコープの
# アトミック操作へ書き換え済みなのに対し、同じ partition.py 内の moveoutput
# だけこの手当てが漏れていた)。
#
# 実害: 唯一の出力 "Mute" が現在 partition A に属しているとする。2クライアント
# 接続 X (partition B に所属) と Y (partition C に所属) がほぼ同時に
# `moveoutput Mute` を送ると、両方とも `output_partition_get("Mute")` で
# "A" を読み取り、それぞれの `dest` (B/C) と比較して「違う」と判定してから
# `output_partition_move()` を呼ぶ。後勝ちの書き込みが先勝ちの結果を無条件で
# 上書きするため、例えば X→B が先に書き込まれた直後に Y→C が上書きすると、
# X 側は「moveoutput が OK を返した」にも関わらず実際には出力は C (Y の
# partition) に属したままになる。ACK エラーは一切出ないサイレントな
# ロストアップデートで、以後 `outputs`/`listpartitions` を見るまで X は
# 自分の partition に出力が実際には移動していないことに気付けない。
#
# 修正: mount_try_add()/partition_try_create()/partition_try_delete() と同じ
# 流儀で、現在の所属確認・比較・書き込みを1つの translator.py 側関数
# output_partition_try_move() にまとめ _partition_lock を1回だけ保持したまま
# 最後まで実行する。partition.py 側は返ってきた状態文字列に応じて元と同じ
# ACK メッセージ・通知タイミングで分岐するだけにする。

import ast

TRANSLATOR = "mopidy_mpd/translator.py"
PARTITION = "mopidy_mpd/protocol/partition.py"

# --- translator.py: output_partition_try_move() を追加 ---
s = open(TRANSLATOR).read()

MARKER = "def output_partition_try_move("
if MARKER in s:
    print("mpdmoveoutputrace already applied to translator.py, skip")
else:
    OLD = (
        "def output_partition_move(name, dest):\n"
        "    with _partition_lock:\n"
        "        _output_partition[name] = dest\n"
    )
    assert s.count(OLD) == 1, f"OLD(translator) count={s.count(OLD)}"
    NEW = (
        "def output_partition_move(name, dest):\n"
        "    with _partition_lock:\n"
        "        _output_partition[name] = dest\n"
        "\n"
        "\n"
        "def output_partition_try_move(name, dest):\n"
        "    # moveoutputハンドラの現在の所属確認+比較+移動を単一ロックで\n"
        "    # 直列化するTOCTOU対策 (mpdpartitiondeltoctou-patch.pyの\n"
        "    # partition_try_delete()と同じ流儀)。個別に呼ぶと、2接続が\n"
        "    # ほぼ同時に異なるdestへmoveoutputを実行した場合、双方が\n"
        "    # 「現在の所属はdestと違う」ことを確認した直後に書き込むため\n"
        "    # 後勝ちの書き込みが先勝ちの結果を無条件で上書きし、ACKエラー\n"
        "    # 無しに一方の意図した移動がサイレントに失われる。\n"
        "    with _partition_lock:\n"
        '        if name not in _output_partition:\n'
        '            return "not_found"\n'
        "        if _output_partition[name] != dest:\n"
        "            _output_partition[name] = dest\n"
        '            return "moved"\n'
        '        return "unchanged"\n'
    )
    s = s.replace(OLD, NEW, 1)
    open(TRANSLATOR, "w").write(s)
    ast.parse(s)
    print(
        "patched translator.py: output_partition_try_move()を追加し、"
        "moveoutputの所属確認・比較・移動を単一ロックスコープでアトミックに"
        "実行できるようにした"
    )

# --- partition.py: moveoutput() ハンドラを output_partition_try_move() 経由に変更 ---
s = open(PARTITION).read()

MARKER2 = "translator.output_partition_try_move("
if MARKER2 in s:
    print("mpdmoveoutputrace already applied to partition.py, skip")
else:
    OLD2 = (
        "    current = translator.output_partition_get(name)\n"
        "    if current is None:\n"
        '        raise exceptions.MpdNoExistError("No such output")\n'
        "    dest = translator.partition_get(id(context.session))\n"
        "    if current != dest:\n"
        "        translator.output_partition_move(name, dest)\n"
        '        _mpdpartition_notify("output")\n'
    )
    assert s.count(OLD2) == 1, f"OLD2(partition.py) count={s.count(OLD2)}"
    NEW2 = (
        "    dest = translator.partition_get(id(context.session))\n"
        "    status = translator.output_partition_try_move(name, dest)\n"
        '    if status == "not_found":\n'
        '        raise exceptions.MpdNoExistError("No such output")\n'
        '    if status == "moved":\n'
        '        _mpdpartition_notify("output")\n'
    )
    s = s.replace(OLD2, NEW2, 1)
    open(PARTITION, "w").write(s)
    ast.parse(s)
    print(
        "patched partition.py: moveoutput()ハンドラをoutput_partition_try_move()"
        "経由のアトミックな所属確認+移動に変更し、2接続がほぼ同時に異なる"
        "partitionへmoveoutputした場合のサイレントなロストアップデートを修正"
    )
