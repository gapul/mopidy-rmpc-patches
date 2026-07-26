# YTMusicLibraryProvider.get_distinct() (MPD の `list`/`count ... group`/`stats` が
# 経由するライブラリ登録アーティスト/アルバム/年の列挙処理) が、
# get_library_artists()/get_library_albums() (計3箇所: artist/albumartist分岐、
# album分岐、date分岐) を config 可変の `self.backend.playlist_item_limit`
# (既定100) で呼んでおり、保存アーティスト/保存アルバムが100件を超えるアカウントで
# 101件目以降をエラーもログも無く静かに切り捨てる不具合。
#
# ytlibrarylimit-patch.py が既に修正した browse() の "ytmusic:artist"/"ytmusic:album"
# 分岐は同じ get_library_artists()/get_library_albums() を `limit=None`
# (ytmusicapi が continuation を使い果たすまで全件取得) で呼ぶよう直しており、
# `lsinfo "YouTube Music/Albums"` は全件返るのに `list album`/`count group album`/
# `stats` の albums: だけ playlist_item_limit で頭打ちになるという非対称が残っていた
# (ytlibrarylimit-patch.py 自身のコメントが「get_distinct()側は既にconfig可変の
# playlist_item_limitを使っておりbrowse/as_list側だけ非対称だった」と書いた時点では
# get_distinct() 側のこの頭打ち自体はバグとして認識されていなかった)。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが (Explore サブエージェントへの
# 調査委任を経て) 改めてmopidy_ytmusicのコード品質を再調査して発見した項目。
#
# 実害: dev mopidy(6601, ytmusic実アカウント)で `playlist_item_limit` を小さい値
# (検証用に3) に設定すると、`lsinfo "YouTube Music/Albums"` (browse経路、limit=None)
# は全件返るのに `list album` (get_distinct経由) は3件しか返らないことを実機確認。
# `stats` の albums:/artists: も同じ get_distinct() を経由するため同様に過少報告する。
#
# 修正: get_distinct() 内の該当3箇所を browse() と同じ `limit=None` に変更する
# (playlist.py の get_playlist(bId, limit=playlist_item_limit) 等、1プレイリスト/
# アルバム内のトラック数を絞る他の playlist_item_limit 用途は本項目のスコープ外
# ・意図通りの挙動のため無変更)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD1 = (
    "            try:\n"
    "                library = self.backend.api.get_library_artists(\n"
    "                    limit=self.backend.playlist_item_limit\n"
    "                )\n"
    "            except Exception:\n"
    '                logger.exception("YTMusic failed getting artists from library")\n'
    "                library = []\n"
    "                pass\n"
)
NEW1 = (
    "            try:\n"
    "                library = self.backend.api.get_library_artists(limit=None)\n"
    "            except Exception:\n"
    '                logger.exception("YTMusic failed getting artists from library")\n'
    "                library = []\n"
    "                pass\n"
)

OLD2 = (
    '        elif field == "album":\n'
    "            try:\n"
    "                library = self.backend.api.get_library_albums(\n"
    "                    limit=self.backend.playlist_item_limit\n"
    "                )\n"
    "            except Exception:\n"
    '                logger.exception("YTMusic failed getting albums from library")\n'
    "                library = []\n"
)
NEW2 = (
    '        elif field == "album":\n'
    "            try:\n"
    "                library = self.backend.api.get_library_albums(limit=None)\n"
    "            except Exception:\n"
    '                logger.exception("YTMusic failed getting albums from library")\n'
    "                library = []\n"
)

OLD3 = (
    '        elif field == "date":\n'
    "            try:\n"
    "                library = self.backend.api.get_library_albums(\n"
    "                    limit=self.backend.playlist_item_limit\n"
    "                )\n"
    "            except Exception:\n"
    '                logger.exception("YTMusic failed getting albums from library")\n'
    "                library = []\n"
)
NEW3 = (
    '        elif field == "date":\n'
    "            try:\n"
    "                library = self.backend.api.get_library_albums(limit=None)\n"
    "            except Exception:\n"
    '                logger.exception("YTMusic failed getting albums from library")\n'
    "                library = []\n"
)

if NEW1 in s and NEW2 in s and NEW3 in s:
    print("ytdistinctlimit already applied, skip")
else:
    assert s.count(OLD1) == 1, f"OLD1 count={s.count(OLD1)}"
    s = s.replace(OLD1, NEW1, 1)
    assert s.count(OLD2) == 1, f"OLD2 count={s.count(OLD2)}"
    s = s.replace(OLD2, NEW2, 1)
    assert s.count(OLD3) == 1, f"OLD3 count={s.count(OLD3)}"
    s = s.replace(OLD3, NEW3, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: get_distinct()のartist/album/date分岐(計3箇所)の"
        "get_library_artists/get_library_albums(limit=playlist_item_limit)固定を"
        "limit=None(全件取得)へ修正しlist/count group/statsが100件超のライブラリで"
        "101件目以降をサイレントに切り捨てる不具合を解消"
    )
