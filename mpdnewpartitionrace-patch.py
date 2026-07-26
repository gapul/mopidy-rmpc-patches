# mopidy_mpd/protocol/partition.py の `newpartition {NAME}` ハンドラが、
# 「現在のパーティション数が16 (実MPDの暫定上限、mpdpartition-patch.py参照) 未満か」
# の確認 (`translator.partition_list()` で件数取得) と実際の作成
# (`translator.partition_create(name)`) という**別々**の translator.py 呼び出しで
# 構成されている不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# 再監査して発見した項目 (mpdpartitiondeltoctou-patch.pyがdelpartition側の
# 「存在確認→default判定→クライアント数確認→出力数確認→削除」という複合操作の
# 同型TOCTOUを`partition_try_delete()`で対処済みなのに対し、newpartition側の
# 「件数確認→作成」も全く同じ非アトミック複合操作のまま残っていた)。
#
# `partition_list()`/`partition_create()`はそれぞれ独立に`_partition_lock`を
# 取得・解放するため、両呼び出しの間には隙間がある。2接続がほぼ同時に
# (現在15個などギリギリで)異なる名前の`newpartition`を送ると、両方とも
# 「15 < 16」の判定を通過してから`partition_create()`を呼び、結果パーティション数が
# 17個 (実MPD仕様の上限16を超過) になってしまう。
#
# 修正: mpdpartitiondeltoctou-patch.pyのpartition_try_delete()と同じ流儀で、
# 「存在確認・上限確認・追加」を単一のtranslator.py側関数
# `partition_try_create()`にまとめ`_partition_lock`を1回だけ保持したまま
# 最後まで実行するよう変更 (partition.py側は名前の正規表現バリデーションの後に
# この1関数を呼び、返ってきた状態文字列に応じて元と同じACKメッセージ・
# 優先順位で例外を送出するだけに変更)。旧`partition_create()`はこの1箇所からしか
# 呼ばれていないため置き換えて削除する。

tp = "mopidy_mpd/translator.py"
ts = open(tp).read()

TRANSLATOR_MARKER = "def partition_try_create("
if TRANSLATOR_MARKER in ts:
    print("translator.py already has partition_try_create, skip")
else:
    OLD_CREATE = (
        "def partition_create(name):\n"
        "    with _partition_lock:\n"
        "        if name in _partitions:\n"
        "            return False\n"
        "        _partitions.append(name)\n"
        "        return True\n"
    )
    assert ts.count(OLD_CREATE) == 1, f"OLD_CREATE count={ts.count(OLD_CREATE)}"

    NEW_CREATE = (
        "def partition_try_create(name):\n"
        "    # newpartitionハンドラの存在確認+上限確認+作成を単一ロックで\n"
        "    # 直列化するTOCTOU対策 (mpdpartitiondeltoctou-patch.pyの\n"
        "    # partition_try_delete()と同じ流儀)。個別に呼ぶと、件数が上限未満\n"
        "    # であることを確認した直後・作成実行前に別接続が別名で作成すると\n"
        "    # 実際には上限を超えた個数のパーティションが存在してしまう。\n"
        "    with _partition_lock:\n"
        "        if name in _partitions:\n"
        "            return \"exists\"\n"
        "        if len(_partitions) >= 16:\n"
        "            return \"too_many\"\n"
        "        _partitions.append(name)\n"
        "        return None\n"
    )
    assert NEW_CREATE != OLD_CREATE
    ts = ts.replace(OLD_CREATE, NEW_CREATE, 1)
    open(tp, "w").write(ts)
    print(
        "patched translator.py: partition_create()をpartition_try_create()へ"
        "置き換え、存在確認+上限確認+作成を単一ロックスコープでアトミックに実行"
    )

pp = "mopidy_mpd/protocol/partition.py"
ps = open(pp).read()

PROTOCOL_MARKER = "translator.partition_try_create(name)"
if PROTOCOL_MARKER in ps:
    print("partition.py already uses partition_try_create, skip")
else:
    OLD_HANDLER = (
        "    if not _mpdpartition_name_re.match(name):\n"
        '        raise exceptions.MpdArgError("bad name")\n'
        "    if len(translator.partition_list()) >= 16:\n"
        '        raise exceptions.MpdUnknownError("too many partitions")\n'
        "    if not translator.partition_create(name):\n"
        '        raise exceptions.MpdExistError("name already exists")\n'
        '    _mpdpartition_notify("partition")\n'
    )
    assert ps.count(OLD_HANDLER) == 1, f"OLD_HANDLER count={ps.count(OLD_HANDLER)}"

    NEW_HANDLER = (
        "    if not _mpdpartition_name_re.match(name):\n"
        '        raise exceptions.MpdArgError("bad name")\n'
        "    status = translator.partition_try_create(name)\n"
        '    if status == "too_many":\n'
        '        raise exceptions.MpdUnknownError("too many partitions")\n'
        '    if status == "exists":\n'
        '        raise exceptions.MpdExistError("name already exists")\n'
        '    _mpdpartition_notify("partition")\n'
    )
    assert NEW_HANDLER != OLD_HANDLER
    ps = ps.replace(OLD_HANDLER, NEW_HANDLER, 1)
    open(pp, "w").write(ps)
    print(
        "patched partition.py: newpartition()がpartition_try_create()経由で"
        "存在確認+上限確認+作成をアトミックに実行するよう修正"
    )
