# add/addid/move/moveid/findadd/searchadd/load が共有する POSITION/TO
# パーサ (`_mpd_add_position`/`_mpd_addid_position`/`_mpd_move_to`
# (current_playlist.py)、`_mpd_parse_addpos_position` (music_db.py)、
# `_mpd_load_position` (stored_playlists.py)) が、いずれも数値部分の
# 妥当性チェックに Python の `str.isdigit()` + 素の `int()` を直書きしており、
# 実MPDの共有パーサが持つ2つの検証軸 (ASCII数字限定・UINT32上限チェック) の
# 両方を欠く不具合。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て) 新規発見。
#
# `str.isdigit()` はUnicode対応のため全角数字等も真になる
# (例: `"０".isdigit()` -> True, `int("０")` -> 0)。よって
# `add URI "０"` (全角0) や `moveid "4" "１"` (全角1) が絶対位置として
# 黙って受理・実行されてしまう (実機確認: 修正前はどちらも `OK` で実際に
# キュー操作が実行された)。また Python の `int()` は任意精度のため上限が
# 無く、桁数だけ正しい巨大な数値もパースに成功してしまう。
#
# 実MPD本体 (gh rawで src/protocol/ArgParser.cxx の
# ParseCommandArgUnsigned() を確認、src/command/PositionArg.cxx の
# ParseInsertPosition()/ParseMoveDestination() が数値部分をこれ経由で
# パースする) は `strtoul(s, &endptr, 10)` を使い、`endptr == s`
# (1文字も数字として消費できない = 全角数字などはASCII基準で非数値) または
# 末尾に余分な文字が残る場合 ACK Integer expected を、
# `value > max_value` の場合 ACK Number too large を返す。
#
# mopidy_mpd側では全く同じ real MPD 関数 (ParseCommandArgUnsigned) を
# 参照する兄弟パーサ `protocol.UINT()` は、この2つの検証軸を既に
# `_MPD_STRICT_UINT_RE` (mpdstrictnumparse-patch.py) と `_MPD_UINT_MAX`
# =0xFFFFFFFF チェック (mpduintmax-patch.py) への統合で実装済みであり、
# 兄弟の `_mpd_parse_window()` (music_db.py) も同じ理由でこれへの委譲に
# 修正済み (mpdwindowstrict-patch.py)。しかし本パッチが対象とする5つの
# POSITION/TO パーサだけは、独自に `str.isdigit()`/`int()` を直書きした
# ままで、`UINT()` が持つこの2つの保護のどちらも受けていなかった。
#
# BACKLOG.md全体を `_mpd_add_position`/`_mpd_addid_position`/
# `_mpd_move_to`/`_mpd_parse_addpos_position`/`_mpd_load_position`/
# `isdigit` で検索し、これら5関数自体の数値検証について既存項目が
# 無いことを確認済み (`mpdaddposrace-patch.py`はTOCTOUレースの
# 修正であり、これら関数の数値パース本体には触れていない)。
#
# 修正: 5関数それぞれの数値パース部分を `protocol.UINT()` 呼び出しへ
# 置き換える。current_playlist.py/stored_playlists.pyの3関数は
# `protocol.commands.add(...)`のvalidatorとして使われており、送出した
# ValueErrorは共通フレームワーク側 (`protocol/__init__.py`) で自動的に
# `MpdArgError("incorrect arguments")` へ変換されるため、そのまま
# `protocol.UINT()`の結果を返すだけでよい。music_db.pyの
# `_mpd_parse_addpos_position`はvalidator経由ではなく直接呼び出される
# ため、ValueErrorを捕捉し既存の `MpdArgError("incorrect arguments")`
# へ変換する処理を明示的に残す。
#
# 実機確認 (TCP 6601、mopidy-ytmusic実アカウント):
#   - `add "ytmusic:track:..." "０"` (全角0) が修正前 `OK` (実際に
#     position 0 へ挿入)、修正後 `ACK [2@0] {add} incorrect arguments`
#     に変化。
#   - `moveid "N" "１"` (全角1) が修正前 `OK` (実際に position 1 へ
#     移動)、修正後 `ACK [2@0] {moveid} incorrect arguments` に変化。
#   - `findadd "(...)" position "２"` (全角2)、`load "NAME" "０"` も
#     同様に修正前は黙って受理、修正後はACKに変化することを確認。
#   - 巨大数値 (`"99999999999999999999"`) も5コマンド全てで同様に
#     ACKへ変化することを確認。
#   - 回帰確認: 半角の絶対位置 (`"0"`)、相対位置 (`"+0"`/`"-0"`) は
#     5コマンド全てで修正前後とも変わらず正常に動作、既存の範囲外エラー
#     ("Bad song index"/"Number too large"/"No current song") も無変更。
#     mopidy.logに新規ERROR/Traceback 0件。

CURRENT_PLAYLIST = "mopidy_mpd/protocol/current_playlist.py"
STORED_PLAYLISTS = "mopidy_mpd/protocol/stored_playlists.py"
MUSIC_DB = "mopidy_mpd/protocol/music_db.py"

MARKER = "mpdpositionstrict-patch"


def _patch_simple_position_func(path, func_name, comment_line):
    s = open(path).read()
    new_func = (
        f"def {func_name}(value):\n"
        f"{comment_line}"
        f"    # {MARKER}: 数値部分は protocol.UINT() に委譲し、\n"
        "    # window/RANGE と同じASCII数字限定・UINT32上限チェックを共有する\n"
        "    # (str.isdigit()はUnicode対応のため全角数字等も誤って受理してしまう)。\n"
        '    if value[:1] in ("+", "-"):\n'
        "        return (value[0], protocol.UINT(value[1:]))\n"
        "    return (None, protocol.UINT(value))\n"
    )
    if new_func in s:
        return False
    old_func = (
        f"def {func_name}(value):\n"
        f"{comment_line}"
        '    if value[:1] in ("+", "-"):\n'
        "        rest = value[1:]\n"
        "        if not rest.isdigit():\n"
        '            raise ValueError("Only positive numbers are allowed")\n'
        "        return (value[0], int(rest))\n"
        "    if not value.isdigit():\n"
        '        raise ValueError("Only positive numbers are allowed")\n'
        "    return (None, int(value))\n"
    )
    assert s.count(old_func) == 1, f"{path}:{func_name} old_func count={s.count(old_func)}"
    s = s.replace(old_func, new_func, 1)
    open(path, "w").write(s)
    return True


patched_any = False

patched_any |= _patch_simple_position_func(
    CURRENT_PLAYLIST,
    "_mpd_add_position",
    "    # add の POSITION: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
    "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (addid と同じ書式)。\n",
)
patched_any |= _patch_simple_position_func(
    CURRENT_PLAYLIST,
    "_mpd_addid_position",
    "    # addid の POSITION: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
    "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する。\n",
)
patched_any |= _patch_simple_position_func(
    CURRENT_PLAYLIST,
    "_mpd_move_to",
    "    # move/moveid の TO: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
    "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (add/addid の\n"
    "    # POSITION と同じ書式)。\n",
)
patched_any |= _patch_simple_position_func(
    STORED_PLAYLISTS,
    "_mpd_load_position",
    "    # load の POSITION: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
    "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (add/addid と同じ書式)。\n",
)

# music_db.py の _mpd_parse_addpos_position は validator 経由ではなく直接
# 呼び出されるため、ValueError を明示的に MpdArgError へ変換する必要がある。
s = open(MUSIC_DB).read()
if MARKER not in s:
    old_func = (
        "def _mpd_parse_addpos_position(value):\n"
        "    # findadd/searchadd の position: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
        "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (add/addid/load と同じ書式)。\n"
        '    if value[:1] in ("+", "-"):\n'
        "        rest = value[1:]\n"
        "        if not rest.isdigit():\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "        return (value[0], int(rest))\n"
        '    if not value.isdigit():\n'
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
        "    return (None, int(value))\n"
    )
    assert s.count(old_func) == 1, f"{MUSIC_DB}:_mpd_parse_addpos_position old_func count={s.count(old_func)}"
    new_func = (
        "def _mpd_parse_addpos_position(value):\n"
        "    # findadd/searchadd の position: 絶対位置 (UINT) か、現在曲基準の相対位置\n"
        "    # (`+N`/`-N`) を表す (kind, offset) タプルに変換する (add/addid/load と同じ書式)。\n"
        "    # mpdpositionstrict-patch: 数値部分は protocol.UINT() に委譲し、\n"
        "    # window/RANGE と同じASCII数字限定・UINT32上限チェックを共有する\n"
        "    # (str.isdigit()はUnicode対応のため全角数字等も誤って受理してしまう)。\n"
        '    if value[:1] in ("+", "-"):\n'
        "        try:\n"
        "            return (value[0], protocol.UINT(value[1:]))\n"
        "        except ValueError:\n"
        '            raise exceptions.MpdArgError("incorrect arguments")\n'
        "    try:\n"
        "        return (None, protocol.UINT(value))\n"
        "    except ValueError:\n"
        '        raise exceptions.MpdArgError("incorrect arguments")\n'
    )
    s = s.replace(old_func, new_func, 1)
    open(MUSIC_DB, "w").write(s)
    patched_any = True

if patched_any:
    print(
        "patched current_playlist.py/stored_playlists.py/music_db.py: "
        "add/addid/move/moveid/findadd/searchadd/loadのPOSITION/TOが"
        "全角数字等の非ASCII数値やUINT32上限超過の巨大数値を黙って"
        "受理してしまう不具合を修正 (protocol.UINT()へ委譲)"
    )
else:
    print("position/to strict numeric parsing already present, skip")
