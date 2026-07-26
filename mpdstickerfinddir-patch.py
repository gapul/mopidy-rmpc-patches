# `sticker find {TYPE} {URI} {NAME} ...` (mopidy_mpd/protocol/stickers.py
# `_mpd_sticker_find_ext()`, mpdstickerfind-patch.py が実装) が非空 URI を
# 単純な文字列 `startswith` でしか絞り込んでおらず、ディレクトリ境界(`/`)を
# 考慮していない不具合。`sticker find song "Music/A" rating` を送ると
# "Music/A/song1.mp3" (配下) だけでなく "Music/AB/song2.mp3" (兄弟ディレクトリ、
# 文字列としては前方一致するが配下ではない) まで誤って一致してしまう。
#
# 実MPD本体 (MusicPlayerDaemon/MPD, WebFetchで直接ソース確認)
# `src/sticker/SongSticker.cxx` の `sticker_song_find()`:
#   if (!base_uri.empty()) {
#       /* append slash to base_uri */
#       allocated = AllocatedString{base_uri, "/"sv};
#       base_uri = allocated.c_str();
#   }
#   ...
#   if (!StringStartsWith(i.uri, base_uri)) continue;
# base_uri が空でない場合は必ず末尾に "/" を補ってから前方一致させており、
# 兄弟ディレクトリを除外する。sticker コマンドのdocstring自体も
# 「below the specified directory (URI)」と明記しており、単純な文字列
# 前方一致ではなく配下判定であることが仕様上の前提。
#
# rmpc本体 (mierak/rmpc) の `rmpc sticker find <uri> <key>` CLIサブコマンド
# (src/config/cli.rs StickerCmd::Find, src/core/command.rs) はユーザ指定の
# 任意の非空 URI をそのまま `sticker find` へ渡す唯一の経路であり、
# ディレクトリ境界を期待した設計になっている
# (TUI内部の呼び出しは全て uri="" 固定のため影響しない)。
#
# 修正: URI が空でなければ末尾に "/" を1つ補ってから前方一致させる
# (既に末尾が "/" の場合の二重付与は避ける)。

p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "mpdstickerfinddir-patch.py: 実MPD"
if MARKER in s:
    print("stickers.py sticker find directory boundary already patched, skip")
else:
    old = (
        "    matches = []\n"
        "    for row_uri, row_value in rows:\n"
        "        if uri and not row_uri.startswith(uri):\n"
        "            continue\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "    matches = []\n"
        "    # mpdstickerfinddir-patch.py: 実MPD (SongSticker.cxx sticker_song_find)\n"
        "    # と同じくディレクトリ境界で判定する。単純な文字列前方一致だと\n"
        '    # uri="Music/A" が"Music/AB/song.mp3"のような兄弟ディレクトリの\n'
        "    # 曲まで誤って一致してしまう。\n"
        "    uri_prefix = (uri if uri.endswith(\"/\") else uri + \"/\") if uri else uri\n"
        "    for row_uri, row_value in rows:\n"
        "        if uri_prefix and not row_uri.startswith(uri_prefix):\n"
        "            continue\n"
    )
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print(
        "patched stickers.py: sticker findが非空URIで兄弟ディレクトリまで"
        "誤って一致する不具合を修正しディレクトリ境界(末尾/)で判定するよう変更"
    )
