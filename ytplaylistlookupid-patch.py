# mopidy_ytmusic/playlist.py の YTMusicPlaylistsProvider.lookup() が、要求した
# playlistId (bId、URIから解決済みで既知正しい値) を使わず、api.get_playlist()の
# 応答に含まれる pls["id"] から返却 Playlist.uri を再構築してしまう不具合。TODO/
# 既知の残課題を全項目消化済みのため自走エージェントが新規発見・追加した項目。
#
# ytmusicapi 1.12.0 (mixins/playlists.py get_playlist()) のソースを実際に確認した
# ところ、playlist["id"] の由来は owned/非owned で全く異なる:
#   - 自分が作成した(owned)プレイリスト: EDITABLE_PLAYLIST_DETAIL_HEADER 配下の
#     PLAYLIST_ID から取得。これは要求時の browseId (= "VL"+bId) に対応する
#     実プレイリストIDそのもので bId と一致する。
#   - 他者作成でライブラリに保存しただけ(非owned)のプレイリスト: RESPONSIVE_HEADER
#     の "buttons" 内 musicPlayButtonRenderer.playNavigationEndpoint から
#     WATCH_PLAYLIST_ID を nav(..., True) (キー欠落時 None を許容) で取得する別物。
#     これは「このプレイリストを再生した場合のwatchプレイリストID」であり、
#     None になることも、要求した bId とは異なる別ID (ラジオ/ミックスID等) に
#     なることもある。YouTube Musicで他者の公開プレイリストを「保存」してライブラリに
#     加える操作は一般的でありowned=Falseは珍しくないケース。
#
# mopidy_mpd/protocol/stored_playlists.py の _get_playlist() は
# context.core.playlists.lookup(uri) の戻り値をそのまま playlistadd/playlistclear/
# playlistdelete/playlistmove/rename/save 等あらゆる編集系MPDコマンドの起点として
# 使い、.replace(...)した上で context.core.playlists.save(playlist) へ渡す。save()は
# bId = parse_uri(playlist.uri) で対象を再解決するため、lookup()がpls["id"]由来の
# 壊れたURIを返すと、非owned(ライブラリ保存)プレイリストへのrmpc経由の編集操作
# (リネーム・曲追加・並べ替え・クリア等)は全て、pls["id"]がNoneなら
# get_playlist("None", ...)の失敗によるサイレントな編集無視、pls["id"]が別の実在ID
# なら全く無関係なプレイリスト/ラジオへの誤動作という、いずれにせよ静かに壊れた
# 挙動になる。as_list()/create()は既に pls["playlistId"]/bId (要求id) からURIを
# 組み立てておりこの問題が無く、lookup()だけが非対称だった。
#
# 修正: lookup() の返却 uri を、応答の pls["id"] ではなく要求時に確定している
# bId (as_list()/save()と同じ「要求id」の流儀) から組み立てる。
p = "mopidy_ytmusic/playlist.py"
s = open(p).read()

MARKER = "非owned(ライブラリ保存)プレイリストでは"
OLD_ANCHOR = '''    def lookup(self, uri):
        bId = parse_uri(uri)
        logger.debug('YTMusic looking up playlist "%s"', bId)
        try:
            pls = self.backend.api.get_playlist(
                bId, limit=self.backend.playlist_item_limit
            )
        except Exception:
            logger.exception("YTMusic playlist lookup failed")
            pls = None
        if pls:
            tracks = self.backend.library.playlistToTracks(pls)
            return Playlist(
                uri=f"ytmusic:playlist:{pls['id']}",
                name=pls["title"],
                tracks=tracks,
                last_modified=None,
            )'''
if MARKER in s:
    print("lookup() bId-based uri already patched, skip")
else:
    NEW = '''    def lookup(self, uri):
        bId = parse_uri(uri)
        logger.debug('YTMusic looking up playlist "%s"', bId)
        try:
            pls = self.backend.api.get_playlist(
                bId, limit=self.backend.playlist_item_limit
            )
        except Exception:
            logger.exception("YTMusic playlist lookup failed")
            pls = None
        if pls:
            tracks = self.backend.library.playlistToTracks(pls)
            # pls["id"](応答由来)ではなく bId(要求id、as_list()/save()と同じ流儀)を
            # 使う。非owned(ライブラリ保存)プレイリストではpls["id"]はwatchプレイ
            # リストID(None/別IDになりうる)であり実プレイリストIDではない。
            return Playlist(
                uri=f"ytmusic:playlist:{bId}",
                name=pls["title"],
                tracks=tracks,
                last_modified=None,
            )'''

    assert s.count(OLD_ANCHOR) == 1, (
        f"expected 1 occurrence of lookup() anchor (got {s.count(OLD_ANCHOR)})"
    )
    s = s.replace(OLD_ANCHOR, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched playlist.py: lookup() が非owned(ライブラリ保存)プレイリストで"
        "応答由来のpls['id'](watchプレイリストID、None/別IDになりうる)からURIを"
        "組み立て編集系MPDコマンドを静かに壊す不具合を修正、要求id(bId)へ統一"
    )
