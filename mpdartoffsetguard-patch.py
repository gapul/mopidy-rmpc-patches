# mopidy_mpd/protocol/connection.py の albumart/readpicture (mpd-patch.py が追加) が
# 共有する `_mpdart_send()` は、クライアント指定の OFFSET が画像の実サイズ (total) を
# 超えている場合を一切検証していない。現行実装は
# `chunk = b'' if offset >= total else data[offset:offset + limit]` で
# `offset >= total` を一律「転送完了(空バイナリ)」として常に OK を返してしまう。
#
# 実MPD本体 (gh raw で src/command/FileCommands.cxx を確認) はこの2コマンドとも
# offset がサイズを超えた場合を明確に ACK_ERROR_ARG(2) で拒否する:
#   - albumart (read_stream_art()): `if (offset > art_file_size) r.Error(ACK_ERROR_ARG,
#     "Offset too large")`
#   - readpicture (PrintPictureHandler::OnPicture()/RethrowError()):
#     `if (offset > buffer.size()) bad_offset = true` -> `ProtocolError(ACK_ERROR_ARG,
#     "Bad file offset")`
# どちらも `offset == total` (=残り0バイトちょうど) のみ空バイナリで OK を許容し、
# `offset > total` のみを拒否する非対称ではない共通の境界だが、エラーメッセージ文言は
# コマンドごとに異なる ("Offset too large" vs "Bad file offset")。
#
# TODO 全項目消化済みのため自走エージェントが (general-purpose サブエージェントへの
# 調査委任を経て) 新規発見。隣接する mpdreadpictureempty-patch.py は「画像取得自体が
# 失敗した場合」のACK非対称のみを修正しており、offsetの境界チェックには未着手だった。
#
# 修正: `total = len(data)` 直後に `offset > total` のガードを追加し、with_type
# (readpicture かどうか) に応じて実MPDと同じエラーメッセージで MpdArgError
# (ACK_ERROR_ARG) を送出する。`offset == total` の既存の空バイナリ応答は無変更。

p = "mopidy_mpd/protocol/connection.py"
s = open(p).read()

MARKER = "Bad file offset"
if MARKER in s:
    print("mpdartoffsetguard already applied to connection.py, skip")
else:
    old = (
        "    total = len(data)\n"
        "    limit = getattr(context.session, 'binary_limit', 8192) or 8192\n"
        "    # 全読了後 rmpc は offset==total で最終確認する。エラーにせず空バイナリを返す。\n"
        "    chunk = b'' if offset >= total else data[offset:offset + limit]\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "    total = len(data)\n"
        "    if offset > total:\n"
        "        # 実MPD (FileCommands.cxx) はoffsetがサイズ超過の場合ACKで拒否する。\n"
        "        # albumart: read_stream_art() \"Offset too large\"、readpicture:\n"
        "        # PrintPictureHandler \"Bad file offset\"。offset==totalは空バイナリのまま。\n"
        "        if with_type:\n"
        "            raise exceptions.MpdArgError('Bad file offset')\n"
        "        raise exceptions.MpdArgError('Offset too large')\n"
        "    limit = getattr(context.session, 'binary_limit', 8192) or 8192\n"
        "    # 全読了後 rmpc は offset==total で最終確認する。エラーにせず空バイナリを返す。\n"
        "    chunk = b'' if offset >= total else data[offset:offset + limit]\n"
    )
    s = s.replace(old, new, 1)

    open(p, "w").write(s)
    print(
        "patched connection.py: albumart/readpictureがOFFSETが画像サイズを超えても"
        "常にOK(空バイナリ)を返してしまう不具合を修正。実MPD本体(FileCommands.cxx)は"
        "offset>totalを明確にACK_ERROR_ARGで拒否する(albumart: \"Offset too large\"、"
        "readpicture: \"Bad file offset\")"
    )
