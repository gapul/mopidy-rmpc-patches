# `sticker set {TYPE} {URI} {NAME} {VALUE}` が NAME 空文字列を検証せず、
# 無条件で OK を返し sticker.db に name="" の行を作成・永続化してしまう不具合を修正。
# TODO全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。
#
# 実MPD本体(gh rawでsrc/command/StickerCommands.cxx handle_sticker()を直接取得し確認)は
# set/inc/dec の3コマンドとも同一の `if (StringIsEmpty(sticker_name)) { r.FmtError(
# ACK_ERROR_ARG, "empty sticker name"); ... }` ガードを持つ。mopidy_mpd側では
# mpdstickernames-patch.py導入時にinc/dec(_mpd_sticker_inc_dec、MPD0.24で新規追加)には
# `if not name: raise exceptions.MpdArgError("empty sticker name")` が移植されたが、
# set(_mpd_sticker_set、mpdsticker-patch.py由来のより古い実装)には同じチェックが
# 一度も移植されず取り残されていた。
#
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント): 実在するtrack URIに対し
# `sticker set song "<uri>" "" "5"` が修正前は OK を返し、直後の
# `sticker list song "<uri>"` に `sticker: =5` という壊れた行が現れることを確認済み
# (実MPDなら `ACK [2@0] {sticker} empty sticker name` で弾かれるべき)。
#
# 修正: `_mpd_sticker_inc_dec()` と同一文言のガードを `_mpd_sticker_set()` の
# 先頭に追加。

import ast

p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "sticker set の NAME 空文字列ガード"
if MARKER in s:
    print("sticker set empty-name guard already present, skip")
else:
    old_fn_head = (
        "def _mpd_sticker_set(context, field, uri, name, value):\n"
        "    conn = _mpd_sticker_conn(context)\n"
    )
    assert s.count(old_fn_head) == 1, f"old_fn_head count={s.count(old_fn_head)}"
    new_fn_head = (
        "def _mpd_sticker_set(context, field, uri, name, value):\n"
        "    # sticker set の NAME 空文字列ガード (実MPD StickerCommands.cxx の\n"
        "    # set/inc/dec 共通の StringIsEmpty(sticker_name) チェックと同じ)\n"
        "    if not name:\n"
        '        raise exceptions.MpdArgError("empty sticker name")\n'
        "    conn = _mpd_sticker_conn(context)\n"
    )
    s = s.replace(old_fn_head, new_fn_head, 1)

    open(p, "w").write(s)
    ast.parse(s)
    print(
        "patched stickers.py: sticker set の NAME空文字列チェック欠落を修正"
    )
