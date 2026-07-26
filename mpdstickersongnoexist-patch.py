# `sticker get/set/delete/list/inc/dec song {URI}` が、存在しない曲URIに対して
# ACK_ERROR_ARG(2)を返している(mpdstickersongvalidate-patch.pyが実装)が、実MPD
# 本体では songドメインの「存在しない」は ACK_ERROR_NO_EXIST(50) が正しく、ACK
# コードが実MPDと異なる不具合を修正。TODO全項目消化済みのため自走エージェントが
# (general-purposeサブエージェントへの調査委任を経て)新規発見。
#
# mpdstickersongvalidate-patch.py 自身のコメントは「SongHandler::ValidateUri()は
# database.GetSong(uri)でstd::invalid_argumentを送出しACK_ERROR_ARG(2)になる、
# playlistドメインと揃える」としていたが、これは実MPD本体のソースの誤読だった。
# 実際には(gh rawでsrc/db/plugins/simple/SimpleDatabasePlugin.cxx GetSong()を
# 確認)存在しないURIに対しGetSong()が送出するのは
# `throw DatabaseError(DatabaseErrorCode::NOT_FOUND, "No such song")`であり、
# std::invalid_argumentではない。src/command/CommandError.cxx の
# `ToAck(DatabaseErrorCode)`は`NOT_FOUND`を`ACK_ERROR_NO_EXIST`(50)に写像する
# (`CONFLICT`のみACK_ERROR_ARG)。playlistドメインの`PlaylistHandler::ValidateUri`
# は`ListPlaylistFiles()`ベースの実装で確かに`std::invalid_argument`
# (→ACK_ERROR_ARG=2)を送出するため、songとplaylistは実MPDでは異なるACKコードを
# 返す非対称仕様であり、mpdstickersongvalidate-patch.pyが両方をACK 2に揃えたのは
# 誤り。mopidy_mpd内の他の「存在しない曲」判定(mpdaddid-patch.py/mpdmoveto-patch.py
# /mpdprio-patch.py/mpdrangeid-patch.py等多数)は一貫して
# `exceptions.MpdNoExistError("No such song")`(ACK 50)を使っており、
# stickers.pyのsong分岐だけがこの規約から外れていた。
#
# 実機確認(TCP 6601、mopidy-ytmusic実アカウント): 存在しないURI
# `sticker set song "ytmusic:track:doesnotexist000000" rating "5"` が
# `ACK [2@0] {sticker} no such song: ...` を返す(実MPDなら
# `ACK [50@0] {sticker} No such song`になるべき)ことを確認済み。
#
# 修正: `_mpd_sticker_validate_uri()`のsongドメイン分岐のみ、送出する例外を
# `exceptions.MpdArgError` から `exceptions.MpdNoExistError` へ変更。playlist
# ドメイン分岐(`MpdArgError`のまま、実MPD準拠)は無変更。

import ast

p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = 'raise exceptions.MpdNoExistError(f"no such song: {uri}")'
if MARKER in s:
    print("stickers.py sticker song ACK code already fixed, skip")
else:
    OLD = (
        "        if not any(lookup_res.values()):\n"
        '            raise exceptions.MpdArgError(f"no such song: {uri}")\n'
    )
    assert s.count(OLD) == 1, f"OLD count={s.count(OLD)}"
    NEW = (
        "        if not any(lookup_res.values()):\n"
        '            raise exceptions.MpdNoExistError(f"no such song: {uri}")\n'
    )
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    ast.parse(s)
    print(
        "patched stickers.py: sticker song ドメインの存在しないURIに対する"
        "ACKコードを実MPD準拠(50)へ修正"
    )
