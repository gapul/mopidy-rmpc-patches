# mopidy_mpd/protocol/stored_playlists.py の `_check_playlist_name()` (save/rename/
# playlistadd/playlistclear/rm/listplaylist/listplaylistinfo が共通で使う
# プレイリスト名バリデータ) が `/`・`\n`・`\r` の3文字種しか弾いておらず、空文字列/
# 空白のみの名前 (例: `save ""`、`save "   "`) を素通ししてしまう不具合。加えて
# mopidy_mpd/protocol/music_db.py の `searchaddpl {NAME} ...` はこの
# `_check_playlist_name()` を一度も呼んでおらず (save/rename/playlistadd/
# playlistclear/rm と非対称)、同じ空文字列問題に加えバリデーション自体が完全に
# 欠落している。TODO 全項目消化済みのため自走エージェントが dev mopidy を実際に
# 起動しMPDプロトコルを叩いて新規発見した項目。
#
# 実害: 空/空白のみの名前で `save`/`searchaddpl` 等を実行すると `OK` が返るが、
# 既定の保存先である mopidy.m3u.playlists の create()/save() は
# `name.strip()` が空文字列になった時点でファイル名が拡張子のみ (例: ".m3u8")
# の隠しファイル (dotfile) になる。Python の pathlib は先頭がドットのみの
# ファイル名を「拡張子なし」として扱う仕様のため、mopidy.m3u.playlists.
# M3UPlaylistsProvider.as_list() の `entry.suffix not in [".m3u", ".m3u8"]`
# フィルタに常に弾かれ、このプレイリストは `listplaylists`/`listplaylistinfo` に
# 二度と現れず、`rm`/`rename` 等の名前引き経路 (`context.
# lookup_playlist_uri_from_name()`は as_list() 由来) でも見つけられないため
# `rm` で消すことも出来ない。空/空白違いの複数の名前 (`""`/`"   "`/`" "`等) は
# 全て同じ1個の隠しファイルへ収束するため、それらを `save` するたびに
# 気付かれないままサイレントに上書きされ続ける、永久に不可視・操作不能な
# ゴースト状態になる (rmpc 側で「新規プレイリスト名」欄が空のまま保存ボタンを
# 押してしまった場合などに実際に踏みうる)。実 MPD の C 実装は拡張子付き
# ファイル名を素朴な文字列末尾一致で探すため空名前でも一覧に出てくる可能性が
# 高く、この不可視化は mopidy 側 (pathlib の dotfile 特別扱い) 由来の
# 非互換であり、rmpc との互換性を保つ本パッチスクリプト群の目的に反する。
#
# 修正方針: 実 MPD 互換の「空名前でも一覧に出るが分かりにくい」動作を再現する
# のではなく、他の多数の *guard-patch.py と同じく安全側に倒し、空/空白のみの
# 名前は `ACK` で明示的に拒否してゴーストファイルの発生自体を防ぐ。
# `_check_playlist_name()` に空文字列 (strip後) チェックを追加し、
# save/rename/playlistadd/playlistclear/rm/listplaylist/listplaylistinfo の
# 7コマンドを一括で保護する。searchaddpl は stored_playlists.py が
# music_db.py の関数を import する一方向の依存関係 (逆方向にすると循環import)
# のため `_check_playlist_name()` を import せず、同じ正規表現ガードを
# music_db.py 内に直接複製して searchaddpl() の先頭に追加する。

import ast

STORED_PLAYLISTS = "mopidy_mpd/protocol/stored_playlists.py"
MUSIC_DB = "mopidy_mpd/protocol/music_db.py"

# --- stored_playlists.py: _check_playlist_name() に空/空白のみチェックを追加 ---
s = open(STORED_PLAYLISTS).read()

NEW_CHECK = (
    'def _check_playlist_name(name):\n'
    '    if not name.strip():\n'
    '        raise exceptions.MpdArgError("Bad playlist name")\n'
    '    if re.search("[/\\n\\r]", name):\n'
    '        raise exceptions.MpdInvalidPlaylistName()\n'
)

if NEW_CHECK in s:
    print("_check_playlist_name() empty-name guard already patched, skip")
else:
    OLD_CHECK = (
        'def _check_playlist_name(name):\n'
        '    if re.search("[/\\n\\r]", name):\n'
        '        raise exceptions.MpdInvalidPlaylistName()\n'
    )
    assert s.count(OLD_CHECK) == 1, f"OLD_CHECK count={s.count(OLD_CHECK)}"
    s = s.replace(OLD_CHECK, NEW_CHECK, 1)

    open(STORED_PLAYLISTS, "w").write(s)
    ast.parse(s)
    print(
        "patched stored_playlists.py: _check_playlist_name()が空/空白のみの"
        "プレイリスト名を素通しし、隠しファイル化で listplaylists から永久に"
        "不可視・操作不能になる不具合を修正 (save/rename/playlistadd/"
        "playlistclear/rm/listplaylist/listplaylistinfoを一括保護)"
    )

# --- music_db.py: searchaddpl() に同じガードを追加 (_check_playlist_name未呼び出し) ---
s = open(MUSIC_DB).read()

NEW_SEARCHADDPL_HEAD = (
    '    playlist_name = parameters.pop(0)\n'
    '    if not playlist_name.strip() or re.search("[/\\n\\r]", playlist_name):\n'
    '        raise exceptions.MpdArgError("Bad playlist name")\n'
)

if NEW_SEARCHADDPL_HEAD in s:
    print("searchaddpl() playlist name guard already patched, skip")
else:
    OLD_SEARCHADDPL_HEAD = '    playlist_name = parameters.pop(0)\n'
    assert s.count(OLD_SEARCHADDPL_HEAD) == 1, f"OLD_SEARCHADDPL_HEAD count={s.count(OLD_SEARCHADDPL_HEAD)}"
    s = s.replace(OLD_SEARCHADDPL_HEAD, NEW_SEARCHADDPL_HEAD, 1)

    open(MUSIC_DB, "w").write(s)
    ast.parse(s)
    print(
        "patched music_db.py: searchaddpl()がstored_playlists.pyの"
        "_check_playlist_name()を一度も呼んでおらず、save/rename等と非対称に"
        "空/空白のみのプレイリスト名を素通ししていた不具合を修正 "
        "(循環import回避のため同じ正規表現ガードを直接複製)"
    )
