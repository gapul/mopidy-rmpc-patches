# `sticker find playlist {URI} {NAME}` が常に0件を返す不具合を修正。TODO全項目
# 消化済みのため自走エージェントが(general-purposeサブエージェントへの調査委任を経て)
# 新規発見。mpdstickerfinddir-patch.py は `sticker find song {URI} ...` の非空URIを
# ディレクトリ境界(末尾"/"付与)で前方一致させるよう修正したが、この処理は
# mpdstickerplaylist-patch.py がplaylistドメインを追加した際、field(TYPE)による
# 分岐なしにそのまま流用されてしまっている。playlistドメインのURIはプレイリスト名
# そのもの(階層構造を持たない平坦な識別子)のため、非空URIに"/"を強制付与すると
# 完全一致検索(例: `sticker set playlist "MyList" rating "5"` の直後に
# `sticker find playlist "MyList" rating` を実行)が
# `"MyList".startswith("MyList/")` = False で必ず外れ、常に0件(ACKにはならない、
# もっとも気付きにくい「正常応答だが常に空」型のバグ)になる。
#
# 実MPD本体 (MusicPlayerDaemon/MPD, gh rawでソース直接確認) では、ディレクトリ境界
# 付与は `src/sticker/SongSticker.cxx` の `sticker_song_find()` (songドメイン専用)
# だけが行う特別扱いであり、`src/command/StickerCommands.cxx` の
# `PlaylistHandler`/`TagHandler`/`FilterHandler` は基底 `DomainHandler::Find()` を
# オーバーライドせず `sticker_database.Find(sticker_type, uri, ...)` へ生のuriを
# そのまま渡す。`src/sticker/Database.cxx` のSQL (`uri LIKE (? || '%')`) は
# 全ドメイン共通の単純前方一致で、スラッシュ付与を行わない。
#
# 修正: field(TYPE)がsongドメインの場合のみ末尾"/"を付与し、それ以外
# (playlist等)は生のuriをそのまま前方一致に使う。

p = "mopidy_mpd/protocol/stickers.py"
s = open(p).read()

MARKER = "mpdstickerplaylistfind-patch.py: このディレクトリ境界"
if MARKER in s:
    print("stickers.py sticker find playlist domain prefix already patched, skip")
else:
    old = (
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
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "    matches = []\n"
        "    # mpdstickerfinddir-patch.py: 実MPD (SongSticker.cxx sticker_song_find)\n"
        "    # と同じくディレクトリ境界で判定する。単純な文字列前方一致だと\n"
        '    # uri="Music/A" が"Music/AB/song.mp3"のような兄弟ディレクトリの\n'
        "    # 曲まで誤って一致してしまう。\n"
        "    # mpdstickerplaylistfind-patch.py: このディレクトリ境界(末尾\"/\"付与)は\n"
        "    # 実MPDでもsongドメイン専用(SongHandler::Find)の特別扱いであり、他の\n"
        "    # ドメイン(playlist等)はDomainHandler::Find の生の前方一致のまま\n"
        '    # (Database.cxx: `uri LIKE (? || \'%\')`, スラッシュ付与なし)。\n'
        "    if field == _MPD_STICKER_TYPE:\n"
        "        uri_prefix = (\n"
        "            (uri if uri.endswith(\"/\") else uri + \"/\") if uri else uri\n"
        "        )\n"
        "    else:\n"
        "        uri_prefix = uri\n"
        "    for row_uri, row_value in rows:\n"
        "        if uri_prefix and not row_uri.startswith(uri_prefix):\n"
        "            continue\n"
    )
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print(
        "patched stickers.py: sticker find playlistが完全一致名でも常に0件になる"
        "不具合を修正しsongドメインのみディレクトリ境界を適用するよう変更"
    )
