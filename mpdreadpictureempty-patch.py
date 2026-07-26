# mopidy_mpd/protocol/connection.py の albumart/readpicture (mpd-patch.py が追加) は
# `_mpdart_send()` を完全に共有しており、画像取得に失敗した (`_mpdart_bytes()` が
# None/空を返す) 場合は常に `MpdNoExistError('No file exists')` を送出しACKにして
# しまう。実MPD本体 (src/command/FileCommands.cxx) を確認すると、この2コマンドの
# 「見つからない場合」の応答は意図的に非対称: `handle_album_art()` は該当箇所が
# 見つからない場合に明示的に `r.Error(ACK_ERROR_NO_EXIST, "No art file exists")`
# を投げるが、`handle_read_picture()` は `PrintPictureHandler::OnPicture()` が
# 一度も呼ばれなくても (`found` が false のまま) 常に `CommandResult::OK` を返す
# のみで、何も出力しない完全な空応答になる (offsetが画像サイズを超えた場合の
# `ACK_ERROR_ARG "Bad file offset"` のみ例外)。mpd.readthedocs.io の readpicture
# 節も「If the song file was recognized, but there is no picture, the response
# is successful, but is otherwise empty.」と明記している。
#
# TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (raw.githubusercontent.com経由でFileCommands.cxxを直接取得し) 新規発見。
# BACKLOG.md中の既存のalbumart/readpicture関連記述 (mpdalbumartnegcache-patch.py
# 等) はいずれも失敗時のACK応答自体を「回帰なしの正しい既存動作」の前提として
# 検証しており、この非対称性には未着手だった。
#
# 実害: mopidy_ytmusic の library.get_images() はアルバム情報欠落/地域制限等で
# 画像を取得できない曲に対して空リストを返すだけで、実際に存在し再生可能な曲でも
# readpictureがACKになってしまう。rmpc既定のAlbumArtOrder::EmbeddedFirstは
# readpictureがACK50(NoExist)の場合のみalbumartへフォールバックする設計のため
# 実害は無い(空OK応答でも同様にフォールバックする実装であることをrmpc-shared/
# src/mpd_client_ext.rsで確認済み)が、プロトコル準拠という観点で実MPDと異なる
# 応答を返している点を修正する。
#
# 修正: `_mpdart_send()` のfalsy分岐を `with_type` (readpicture) かどうかで分岐。
# readpicture (with_type=True) は例外を投げず戻り値Noneのみ返す (何もqueue_send
# しない、完全な空OK応答)。albumart (with_type=False) は現状通りACKのまま。

p = "mopidy_mpd/protocol/connection.py"
s = open(p).read()

MARKER = "readpictureは空OK"
if MARKER in s:
    print("mpdreadpictureempty already applied to connection.py, skip")
else:
    old = (
        "def _mpdart_send(context, uri, offset, with_type):\n"
        "    data = _mpdart_bytes(context, uri)\n"
        "    if not data:\n"
        "        raise exceptions.MpdNoExistError('No file exists')\n"
        "    total = len(data)\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "def _mpdart_send(context, uri, offset, with_type):\n"
        "    data = _mpdart_bytes(context, uri)\n"
        "    if not data:\n"
        "        # readpictureは空OK (実MPD handle_read_picture()はfoundがfalseの\n"
        "        # ままでもCommandResult::OK、何も出力しない)、albumartはACKのまま\n"
        "        # (実MPD handle_album_art()はACK_ERROR_NO_EXIST \"No art file exists\")。\n"
        "        if with_type:\n"
        "            return None\n"
        "        raise exceptions.MpdNoExistError('No file exists')\n"
        "    total = len(data)\n"
    )
    s = s.replace(old, new, 1)

    open(p, "w").write(s)
    print(
        "patched connection.py: readpictureが画像取得失敗時にalbumartと"
        "同じACK [50@0] No file existsを返してしまう不具合を修正。実MPD本体"
        "(FileCommands.cxx handle_read_picture()/handle_album_art())は"
        "この2コマンドの「見つからない場合」の応答を意図的に非対称にしており"
        "readpictureは常にOK(空応答)を返す。albumartは現状通りACKのまま"
    )
