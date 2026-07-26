# mopidy_ytmusic.library.py の search() が受け取る query["uri"] (MPD の
# find/search filter "file"/"filename" タグ、mopidy_mpd/protocol/music_db.py の
# TAG_MAP で "file"/"filename" -> "uri" にマップされる、mopidy.core.Library.search()
# のドキュメント上も正式フィールド) 分岐が ytmusic:album: の URI しか扱わず、
# ytmusic:artist:/ytmusic:playlist:/ytmusic:track: の有効な既知 URI を渡しても
# 無条件に None (このバックエンドは非対応、の意味) を返してしまいヒット0件になる
# 不具合を発見。TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが
# mopidy_ytmusicのコード品質を再調査(ytverifytrackurl-patch.py等これまでの一連の
# 発見的パッチと同じ流儀)して発見した項目。
#
# 実MPDでは `find file "<path>"`/`find filename "<path>"` はライブラリが知っている
# 任意の有効なfile(トラック)に対して一致確認ができ、`add`/`findadd`等の内部実装
# でも同じ経路が使われうる。mopidy_ytmusicのlookup()は既にalbum(通常/upload)/
# artist(通常/upload)/playlist/単曲URIの全パターンをtry/except保護つきで解決済みで
# あるにもかかわらず、search()のuri分岐だけそのロジックを再実装せず album のみの
# 劣化コピーになっており、`find file "ytmusic:artist:UCxxx"` や
# `find file "ytmusic:playlist:PLxxx"` や `find file "ytmusic:track:xxx"` が
# 常に空応答になっていた。
#
# 対策: uri分岐をlookup()への委譲に置き換える。lookup()は対象URIの種別を自ら
# 判定しalbum/artist/playlist/track全てを解決するため、重複コードを消しつつ
# 対応範囲をlookup()と同等(=既に個別に検証済み)まで広げられる。ytmusicスキーム
# 以外のURI(他バックエンド宛のfile filter)は従来通りNoneを返しこのバックエンドの
# 管轄外として扱う。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "if uri.startswith(\"ytmusic:\"):\n                tracks = self.lookup(uri)"
if MARKER in s:
    print("library.py already patched (search uri branch), skip")
else:
    OLD = '''        elif "uri" in query:
            uri = query["uri"][0]
            tracks = []
            if uri.startswith("ytmusic:album:"):
                bId, upload = parse_uri(uri)
                if upload:
                    try:
                        res = self.backend.api.get_library_upload_album(bId)
                        tracks = self.uploadAlbumToTracks(res, bId)
                    except Exception:
                        logger.exception(
                            'YTMusic failed getting tracks for uploaded album "%s"',
                            bId,
                        )
                else:
                    try:
                        res = self.backend.api.get_album(bId)
                        tracks = self.albumToTracks(res, bId)
                    except Exception:
                        logger.exception(
                            'YTMusic failed getting tracks for album "%s"', bId
                        )
                tracks = list(tracks)
                for track in tracks:
                    bId, _ = parse_uri(track.uri)
                    self.TRACKS[bId] = track
                results = SearchResult(
                    uri="ytmusic:search",
                    tracks=tracks,
                    artists=list(),
                    albums=list(),
                )
            else:
                return None
'''
    NEW = '''        elif "uri" in query:
            uri = query["uri"][0]
            if uri.startswith("ytmusic:"):
                tracks = self.lookup(uri)
                results = SearchResult(
                    uri="ytmusic:search",
                    tracks=tracks,
                    artists=list(),
                    albums=list(),
                )
            else:
                return None
'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of search() uri-branch anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: search()のuri分岐をlookup()委譲に置き換え、"
        "album限定だったfile/filenameタグ検索をartist/playlist/track含む"
        "既知URI全般に対応"
    )
