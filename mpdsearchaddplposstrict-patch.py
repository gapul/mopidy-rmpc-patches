# `searchaddpl {NAME} {FILTER} [sort {TYPE}] [window {START:END}] [position {POS}]`
# の POSITION パースが `mpdsearchaddplpos-patch.py` で追加された際、他の
# POSITION/TO パーサ (add/addid/move/moveid/findadd/searchadd/load) とは違い、
# 独立した名前付き関数ではなく searchaddpl() 本体にインラインで
# `_position_value.isdigit()` + 素の `int()` を直書きしてしまっていた。
# TODO 全項目消化済みのため自走エージェントが (general-purpose サブエージェントへの
# 調査委任を経て) 新規発見。
#
# `mpdpositionstrict-patch.py` は同種のバグを5関数
# (`_mpd_add_position`/`_mpd_addid_position`/`_mpd_move_to`(current_playlist.py)、
# `_mpd_parse_addpos_position`(music_db.py、findadd/searchadd用)、
# `_mpd_load_position`(stored_playlists.py)) について `protocol.UINT()` への
# 委譲へ一括修正済みだが、対象を名前付き関数5つに限定しており、searchaddpl()の
# インライン処理は対象に含まれていなかった (実際に本パッチ適用前の
# ビルド済みソースを grep して isdigit の直書きが唯一この1箇所に残存している
# ことを確認済み)。BACKLOG.mdをsearchaddpl/isdigitで検索したが、position引数の
# 全角数字/UINT32上限超過値についての既存項目は無い (既存項目は "abc" のような
# 非数値や "999" のような範囲外の絶対値についてのみ検証済み)。
#
# `str.isdigit()` はUnicode対応のため全角数字等も真になり
# (例: `"０".isdigit()` -> True, `int("０")` -> 0) `searchaddpl NAME "(...)"
# position "０"` が全角数字を絶対位置として黙って受理・実行してしまう。
# `int()` は任意精度のためUINT32上限チェックも無い。
#
# 実MPD本体 (gh rawで src/command/DatabaseCommands.cxx handle_searchaddpl() を
# 確認) は POSITION を `ParseQueuePosition(args, UINT_MAX)` 経由で
# パースしており、これは他の position/window/UINT 系コマンドと全く同じ
# `ParseCommandArgUnsigned()` (`strtoul` ベースの共有厳密パーサ) に委譲している。
# mopidy_mpd側で同じ real MPD 関数を参照する兄弟パーサ `protocol.UINT()` は
# 既に ASCII数字限定・UINT32上限チェックの両方を実装済み
# (`mpdstrictnumparse-patch.py`/`mpduintmax-patch.py`) なので、そこへ委譲する。
#
# 修正: searchaddpl() 内の `_position_value.isdigit()` + `int()` を
# `protocol.UINT()` へ置換し、`ValueError` を既存の
# `MpdArgError("incorrect arguments")` へ変換する。
#
# 実機確認 (TCP 6601、mopidy-ytmusic実アカウント):
#   - `searchaddpl NAME "(Artist == \"YOASOBI\")" position "０"` (全角0) が
#     修正前 `OK` (実際に position 0 へ挿入)、修正後
#     `ACK [2@0] {searchaddpl} incorrect arguments` に変化。
#   - `position "99999999999999999999"` (巨大数値) も同様にACKへ変化。
#   - 回帰確認: 半角の絶対位置 (`"0"`/`"1"`)、position 省略 (末尾追加)、
#     既存の "Bad position" (範囲外) は無変更。findadd/searchadd/add/addid/
#     move/moveid/load のPOSITION/TOも無変更。mopidy.logに新規
#     ERROR/Traceback 0件。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

old_block = (
    "    _position = None\n"
    '    if len(parameters) >= 2 and parameters[-2].lower() == "position":\n'
    "        _position_value = parameters[-1]\n"
    "        if not _position_value.isdigit():\n"
    '            raise exceptions.MpdArgError("incorrect arguments")\n'
    "        _position = int(_position_value)\n"
    "        del parameters[-2:]\n"
)

if old_block not in s:
    print("searchaddpl position strict parsing already applied, skip")
else:
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"
    new_block = (
        "    _position = None\n"
        '    if len(parameters) >= 2 and parameters[-2].lower() == "position":\n'
        "        _position_value = parameters[-1]\n"
        "        try:\n"
        "            _position = protocol.UINT(_position_value)\n"
        "        except ValueError:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        del parameters[-2:]\n"
    )
    s = s.replace(old_block, new_block, 1)
    open(p, "w").write(s)
    print(
        "patched music_db.py: searchaddplのインラインPOSITIONパースが"
        "全角数字/UINT32上限超過を黙って受理する不具合を修正 (protocol.UINT()へ委譲)"
    )
