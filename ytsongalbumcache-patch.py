# mopidy_ytmusic.library.py の parseSearch() の resultType=="song" 分岐が、album を
# self.ALBUMS キャッシュへ「新規登録した時だけ」変数へ代入し、既に登録済み(キャッシュ
# ヒット)の場合は album=None のまま Track を組み立ててしまう不具合を発見。
#
# ytstalecache-patch.py (self.TRACKS の陳腐化キャッシュ修正) の対応時に BACKLOG.md へ
# 「今回のスコープ外としてそのまま温存」と明記されていた既知の予備的な癖で、TODO/既知の
# 残課題を全項目消化済みのため自走エージェントが改めて調査し着手した。
#
# 該当コード (parseSearch() song分岐):
#   album = None
#   if result.get("album"):
#       if result["album"]["id"] not in self.ALBUMS:
#           self.ALBUMS[result["album"]["id"]] = Album(...)
#           album = self.ALBUMS[result["album"]["id"]]   # ← if の内側 = 新規登録時のみ実行
#
# `album = self.ALBUMS[...]` が `if ... not in self.ALBUMS:` の内側にネストしているため、
# その album id が既に self.ALBUMS にキャッシュ済み(以前の search/browse で登録済み)だと
# 内側の if が False になり、album 変数は None のまま Track(album=None) が作られる。
# 同じ関数の playlistToTracks() (875-888行目) や、同分岐内のartist経由songsループ
# (「songs」in artistq の分岐) では `album = self.ALBUMS[...]` を if の外側に置いており、
# song分岐だけがこの非対称なバグを持つ。
#
# 実害: search/find の結果に同一アルバムの曲が複数含まれる場合、最初の1曲だけ
# Album/AlbumArtist/X-AlbumUri が正しく付き、2曲目以降は album=None で欠落する。
# さらに、あるアルバムIDが一度でも self.ALBUMS に載る(他のsearch/browse経由でもよい)と、
# 以後そのアルバムのどの曲を song分岐経由で search/find しても mopidy プロセスの残り
# 寿命ずっと album=None になり続け、rmpc の Album によるグルーピング・ナビゲーションが壊れる。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '''                    album = None
                    if result.get("album"):
                        if result["album"]["id"] not in self.ALBUMS:
                            self.ALBUMS[result["album"]["id"]] = Album(
                                uri=f"ytmusic:album:{result['album']['id']}",
                                name=result["album"]["name"],
                                artists=artists,
                                num_tracks=None,
                                num_discs=None,
                                date="0000",
                                musicbrainz_id="",
                            )
                            album = self.ALBUMS[result["album"]["id"]]
                    self.TRACKS[result["videoId"]] = Track('''

NEW = '''                    album = None
                    if result.get("album"):
                        if result["album"]["id"] not in self.ALBUMS:
                            self.ALBUMS[result["album"]["id"]] = Album(
                                uri=f"ytmusic:album:{result['album']['id']}",
                                name=result["album"]["name"],
                                artists=artists,
                                num_tracks=None,
                                num_discs=None,
                                date="0000",
                                musicbrainz_id="",
                            )
                        album = self.ALBUMS[result["album"]["id"]]
                    self.TRACKS[result["videoId"]] = Track('''

assert s.count(OLD) == 1, f"expected 1 occurrence of parseSearch song-branch album-cache anchor (got {s.count(OLD)})"
s = s.replace(OLD, NEW, 1)

open(p, "w").write(s)
print(
    "patched library.py: parseSearch()のsong分岐でALBUMSキャッシュヒット時にalbum変数が"
    "Noneのまま代入されない不具合を修正 (playlistToTracks()と同じ流儀に統一)"
)
