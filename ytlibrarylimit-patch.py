# mopidy_ytmusic.library.YTMusicLibraryProvider.browse() の "ytmusic:artist"/"ytmusic:album"
# 分岐と mopidy_ytmusic.playlist.YTMusicPlaylistsProvider.as_list() が、
# get_library_artists()/get_library_upload_artists()/get_library_albums()/
# get_library_upload_albums()/get_library_playlists() をいずれも `limit=100` 固定で
# 呼んでおり、ytmusicapi 1.12.0 側は `limit=None` で continuation を辿り全件取得できる
# (get_library_playlists の docstring: "``None`` retrieves them all."、
# get_library_upload_albums/upload_artists も同様に明記、get_library_albums/artists は
# 内部の parse_library_albums/parse_library_artists が limit=None を
# `remaining_limit = None` として素通しし無制限に continuation を辿る実装になっている)
# にも関わらず、mopidy_ytmusic は例外もエラーログも出さずに101件目以降を静かに切り捨てる。
#
# 実害: フォローアーティスト/保存アルバム/保存プレイリスト/アップロード済み
# アーティスト・アルバムのいずれかが100件を超えるアカウントで、rmpc から
# `lsinfo "YouTube Music/Artists"` / `lsinfo "YouTube Music/Albums"` / `listplaylists`
# を送ると、実在する101件目以降が理由の分かるログすら残さず消える。
# get_distinct() (list/count の group 列挙経路、ytdistinct-patch.py) は同じ
# get_library_artists()/get_library_albums() 呼び出しに config 可変の
# `self.backend.playlist_item_limit` を使っているのに対し、browse()/as_list() 側だけが
# config と無関係な固定100のままという非対称性があり、`playlist_item_limit` を
# 大きくしても実際のブラウズ結果は100件で頭打ちのままだった。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが改めてmopidy_ytmusicの
# コード品質を再調査して発見した項目。
#
# 修正: 該当5箇所を `limit=None` (全件取得、ytmusicapi が内部で continuation を
# 使い果たすまで回す) に変更。
p1 = "mopidy_ytmusic/library.py"
s1 = open(p1).read()

OLD1 = "for a in self.backend.api.get_library_artists(limit=100)"
NEW1 = "for a in self.backend.api.get_library_artists(limit=None)"

OLD2 = (
    "                        for a in self.backend.api.get_library_upload_artists(\n"
    "                            limit=100\n"
    "                        )\n"
)
NEW2 = (
    "                        for a in self.backend.api.get_library_upload_artists(\n"
    "                            limit=None\n"
    "                        )\n"
)

OLD3 = "for a in self.backend.api.get_library_albums(limit=100)"
NEW3 = "for a in self.backend.api.get_library_albums(limit=None)"

OLD4 = (
    "                        for a in self.backend.api.get_library_upload_albums(\n"
    "                            limit=100\n"
    "                        )\n"
)
NEW4 = (
    "                        for a in self.backend.api.get_library_upload_albums(\n"
    "                            limit=None\n"
    "                        )\n"
)

if NEW1 in s1 and NEW2 in s1 and NEW3 in s1 and NEW4 in s1:
    print("ytlibrarylimit already applied to library.py, skip")
else:
    assert s1.count(OLD1) == 1, f"OLD1 count={s1.count(OLD1)}"
    s1 = s1.replace(OLD1, NEW1, 1)
    assert s1.count(OLD2) == 1, f"OLD2 count={s1.count(OLD2)}"
    s1 = s1.replace(OLD2, NEW2, 1)
    assert s1.count(OLD3) == 1, f"OLD3 count={s1.count(OLD3)}"
    s1 = s1.replace(OLD3, NEW3, 1)
    assert s1.count(OLD4) == 1, f"OLD4 count={s1.count(OLD4)}"
    s1 = s1.replace(OLD4, NEW4, 1)
    open(p1, "w").write(s1)
    print(
        "patched library.py: browse()のartist/album分岐(通常+アップロード計4箇所)の"
        "get_library_*(limit=100)固定を limit=None(全件取得)へ修正し101件目以降の"
        "サイレントな切り捨てを解消"
    )

p2 = "mopidy_ytmusic/playlist.py"
s2 = open(p2).read()

OLD5 = "playlists = self.backend.api.get_library_playlists(limit=100)"
NEW5 = "playlists = self.backend.api.get_library_playlists(limit=None)"

if NEW5 in s2:
    print("ytlibrarylimit already applied to playlist.py, skip")
else:
    assert s2.count(OLD5) == 1, f"OLD5 count={s2.count(OLD5)}"
    s2 = s2.replace(OLD5, NEW5, 1)
    open(p2, "w").write(s2)
    print(
        "patched playlist.py: as_list()のget_library_playlists(limit=100)固定を"
        "limit=None(全件取得)へ修正し101件目以降のプレイリストのサイレントな切り捨てを解消"
    )
