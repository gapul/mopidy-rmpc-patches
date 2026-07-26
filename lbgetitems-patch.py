# mopidy_listenbrainz/playlists.py の ListenbrainzPlaylistsProvider.get_items() が、
# mopidy.backend.PlaylistsProvider.get_items() の契約
# ("Returns a list of Ref objects referring to the playlist's items"、
# 対の mopidy_ytmusic.playlist.YTMusicPlaylistsProvider.get_items() は
# `[Ref.track(uri=t.uri, name=t.name) for t in tracks]` と正しく実装している)
# に反し、プレイリスト "内の曲" (Ref.track) ではなく、マッチした "プレイリスト
# 自身" (Ref.playlist) をそのまま返してしまっている不具合。
#
#     return [Ref.playlist(uri=p.uri, name=p.name) for p in found]
#
# found は「uri が一致するプレイリスト」のリスト (playlists.py の他メソッド同様
# uri をキーとして高々1件) であり、その Playlist オブジェクトを Ref.playlist として
# 素通ししているだけで、found[0].tracks (実際の曲一覧) を一切見ていない。
#
# 実害: core.playlists.get_items(uri) は Mopidy-HTTP の JSON-RPC 経由で任意の
# クライアント (Iris 等の Web UI、本プロジェクトでも [http] enabled=true) から
# 呼び出し可能な公開 API。ListenBrainz の recommendation プレイリスト
# ("listenbrainz:playlist:recommendation:..."、frontend.py の import_playlists()
# が作成) に対しこれを呼ぶと、期待される「プレイリスト内の曲一覧」ではなく
# 「そのプレイリスト自身を指す1件の Ref (しかも type が Track ではなく
# Playlist)」が返り、クライアント側はプレイリストの中身を一切取得できない
# (曲が1件もないかのように振る舞う、または型不一致でクラッシュする)
# サイレントな機能不全となる。import_playlists 機能自体が有効な環境
# (search_schemes 設定込み) であれば常に踏む経路であり、rmpc からは到達しない
# (rmpc は MPD プロトコルのみで stored_playlists.py の _get_playlist() 経由の
# core.playlists.lookup() を使い、get_items() は使わない) が、HTTP-JSONRPC
# (127.0.0.1:6681) 経由の一般的な mopidy クライアントには実害あるギャップ。
#
# 修正: found[0] (uri に一致した唯一のプレイリスト) の tracks を
# Ref.track として返すよう、mopidy_ytmusic の get_items() と同じ形へ揃える。

p = "mopidy_listenbrainz/playlists.py"
s = open(p).read()

OLD = """        found = [p for p in self.playlists if p.uri == uri]
        if len(found) == 0:
            return None

        return [Ref.playlist(uri=p.uri, name=p.name) for p in found]
"""

NEW = """        found = [p for p in self.playlists if p.uri == uri]
        if len(found) == 0:
            return None

        return [Ref.track(uri=t.uri, name=t.name) for t in found[0].tracks]
"""

if NEW in s and OLD not in s:
    print("ListenbrainzPlaylistsProvider.get_items() already returns track refs, skip")
else:
    count = s.count(OLD)
    assert count == 1, f"OLD count={count}"
    s = s.replace(OLD, NEW)
    open(p, "w").write(s)
    print(
        "patched playlists.py: ListenbrainzPlaylistsProvider.get_items() が "
        "プレイリスト内の曲(Ref.track)ではなくプレイリスト自身(Ref.playlist)を "
        "返してしまう不具合を修正"
    )
