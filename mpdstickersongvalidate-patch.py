# `sticker get/set/delete/list/inc/dec song {URI} ...` が、指定URIが実在する曲か
# どうかを一切検証せず、架空(存在しない/typo/スキーム無し不正形式)のURIに対しても
# 無条件で OK を返しスティッカーを永続化してしまう不具合を修正。TODO全項目消化済み
# のため自走エージェントが(general-purposeサブエージェントへの調査委任を経て)
# 新規発見。
#
# mpdstickerplaylist-patch.py が導入した `_mpd_sticker_validate_uri()` は
# playlistドメイン(`context.lookup_playlist_uri_from_name(uri) is None`)の分岐は
# 持つが、songドメインの分岐が存在せず素通しになっている。
#
# 実MPD本体(gh rawでsrc/command/StickerCommands.cxxを直接取得し確認)の
# `SongHandler::ValidateUri()` は `database.GetSong(uri)` でURIがDB上に実在する
# 曲かを検証し、無ければ例外を送出する(`src/command/CommandError.cxx` の
# `ToAck()` で `std::invalid_argument` → `ACK_ERROR_ARG`(2)、`ACK_ERROR_NO_EXIST`
# (50)ではない点、playlistドメインの既存実装と揃える)。この検証は
# Get/Set/Inc/Dec/Delete/List のみで行われ、Find(URIをプレフィックスとして使う)
# では呼ばれない非対称仕様のため、sticker()本体の既存の
# `if action != "find": _mpd_sticker_validate_uri(...)` ガードにそのまま乗る。
#
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント): 存在しないURI
# `sticker set song "ytmusic:track:doesnotexist000000" rating "5"` が修正前は
# OK を返し、直後の `sticker get song ... rating` が `sticker: rating=5` を
# 返してしまう(実MPDなら `ACK [2@0] {sticker} no such song: ...` で弾かれる
# べき)ことを確認済み。`sticker find song "" rating` で実際に架空URIの
# スティッカーが既に混在して返ってくる(rmpcの「評価済み曲一覧」等のUIを
# 静かに汚染しうる)ことも確認済み。
#
# 修正: mpdaddidrawuriguard-patch.py/mpdplaylistaddpos-patch.py 等と同じ既存の
# `context.core.library.lookup(uris=[uri]).get()` パターンをそのまま踏襲し、
# ValidationError(スキーム無し等の不正URI)は空扱いに丸め、lookup結果が
# 空(実在しない曲)なら `MpdArgError` で弾く。

import ast

p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "elif field == _MPD_STICKER_TYPE:"
if MARKER in s:
    print("stickers.py sticker song domain uri validation already present, skip")
else:
    OLD = (
        "def _mpd_sticker_validate_uri(context, field, uri):\n"
        "    if field == _MPD_STICKER_PLAYLIST_TYPE:\n"
        "        if context.lookup_playlist_uri_from_name(uri) is None:\n"
        '            raise exceptions.MpdArgError(f"no such playlist: {uri}")\n'
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    NEW = (
        "def _mpd_sticker_validate_uri(context, field, uri):\n"
        "    if field == _MPD_STICKER_PLAYLIST_TYPE:\n"
        "        if context.lookup_playlist_uri_from_name(uri) is None:\n"
        '            raise exceptions.MpdArgError(f"no such playlist: {uri}")\n'
        "    elif field == _MPD_STICKER_TYPE:\n"
        "        import mopidy.exceptions\n"
        "\n"
        "        try:\n"
        "            lookup_res = context.core.library.lookup(uris=[uri]).get()\n"
        "        except mopidy.exceptions.ValidationError:\n"
        "            # uri がスキーム無し等で mopidy の URI として不正な場合。\n"
        "            # mpdrawuriguard-patch.py と同じ扱いで「そんな曲は無い」に丸める。\n"
        "            lookup_res = {}\n"
        "        if not any(lookup_res.values()):\n"
        '            raise exceptions.MpdArgError(f"no such song: {uri}")\n'
    )
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    ast.parse(s)
    print(
        "patched stickers.py: sticker song ドメインがURIの実在検証をしていなかった"
        "不具合を修正"
    )
