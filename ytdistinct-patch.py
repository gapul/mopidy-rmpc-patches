# mopidy-ytmusic の get_distinct() は field=="album" の分岐が丸ごとコメントアウトされた
# ままで、実装は artist/albumartist (ライブラリ登録アーティストのみ) しか返さない。
# MPD の `list Album` / `list Album group AlbumArtist` 等 album 系グループ化が実データで
# 常に空になってしまうため、ytmusicapi.get_library_albums() を使って有効化する。
# (アップロード分 get_library_upload_albums は artist 分岐でも常時コメントアウトの
#  ままな慣例に合わせ、今回もライブラリ登録分のみに留める)
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '''        # elif field == "album":
        #     try:
        #         uploads = self.backend.api.get_library_upload_albums(limit=self.backend.playlist_item_limit)
        #     except Exception:
        #         logger.exception("YTMusic failed getting uploaded albums")
        #         uploads = []
        #         pass
        #     try:
        #         library = self.backend.api.get_library_albums(limit=self.backend.playlist_item_limit)
        #     except Exception:
        #         logger.exception("YTMusic failed getting albums from library")
        #         library = []
        #         pass
        #     for a in uploads:
        #         ret.add(a["title"])
        #     for a in library:
        #         ret.add(a["title"])
        return ret'''

NEW = '''        elif field == "album":
            try:
                library = self.backend.api.get_library_albums(
                    limit=self.backend.playlist_item_limit
                )
            except Exception:
                logger.exception("YTMusic failed getting albums from library")
                library = []
            for a in library:
                if a.get("title"):
                    ret.add(a["title"])
        return ret'''

assert s.count(OLD) == 1, f"expected 1 occurrence of album get_distinct anchor (got {s.count(OLD)})"
s = s.replace(OLD, NEW, 1)

open(p, "w").write(s)
print("patched library.py: get_distinct(\"album\") をライブラリ登録アルバムで有効化")
