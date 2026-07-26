# mopidy_mpd/uri_mapper.py の MpdUriMapper.playlist_name_from_uri() が
# キャッシュミス後の refresh_playlists_mapping() でも見つからない場合に
# 素の dict インデックス `self._playlist_name_from_uri[uri]` で KeyError を
# 投げる不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# 改めて mopidy_mpd のコード品質を再調査して発見した項目。
#
# 姉妹関数 playlist_uri_from_name() は同じ「キャッシュミス→refresh→再検索」
# パターンで `.get(name)` を使い安全に None を返すのに対し、
# playlist_name_from_uri() だけ `[uri]` の無条件インデックスで非対称になっている。
#
# 実害の引き金: mopidy_ytmusic.playlist.YTMusicPlaylistsProvider.as_list() は
# `self.backend.api.get_library_playlists(limit=100)` (実際にYouTube Musicへ
# 問い合わせるネットワーク呼び出し) が例外を投げた場合に `logger.exception()`
# した上で空リストへフォールバックする設計 (playlist.py 冒頭の try/except)。
# 一方 protocol/stored_playlists.py の listplaylists() は
#   1) `context.core.playlists.as_list().get()` (T1) でプレイリスト一覧を取得
#   2) 各 playlist_ref.uri ごとに `context.lookup_playlist_name_from_uri(uri)`
#      -> uri_mapper.playlist_name_from_uri(uri) を呼ぶ
# という2段構成で、名前キャッシュが空(起動直後等)だと 2) の内部で
# refresh_playlists_mapping() が as_list() を「もう一度」(T2) 呼び直す。
# T1 は成功したのに T2 だけ瞬断/レート制限/クォータ等で失敗すると、
# as_list() は空リストにフォールバックするため refresh_playlists_mapping() は
# 「プレイリストが1つも無くなった」と誤解し current_uris=空集合を基準に
# 既存キャッシュを丸ごと stale 扱いして破棄する。結果、T1 のスナップショットに
# 実在した playlist_ref.uri がキャッシュに無いまま
# `self._playlist_name_from_uri[uri]` に到達し KeyError。
# これは exceptions.MpdAckError のサブクラスではないため
# dispatcher.py の _catch_mpd_ack_errors_filter に捕捉されず、素の Exception が
# pykka アクターの外まで伝播して接続そのものが切断される (rmpc から見れば
# listplaylists を送っただけでサーバーとの接続が落ちる)。
#
# 再現: repro.py で FlakyCore (1回目の as_list() は実データ、2回目=refresh内は
# 瞬断を模した空リストを返す) を用意し、listplaylists() と同じ
# 「outer as_list() → 各 uri を playlist_name_from_uri() で解決」の流れを実行
# したところ、パッチ前は KeyError で例外送出(不具合の実在を確認)。
#
# 修正: playlist_uri_from_name() と対称に `.get(uri)` へ変更し None を安全に
# 返せるようにした上で、唯一の呼び出し元 listplaylists() 側も
# 「名前が無いプレイリストは無視する」という同関数内の既存の流儀
# (`if not playlist_ref.name: continue`) に合わせ、None ならそのエントリだけ
# skip して残りは正常にレンダリングを続ける (1件の瞬断が listplaylists 応答
# 全体・接続を巻き込まないようにする)。

p1 = "mopidy_mpd/uri_mapper.py"
s1 = open(p1).read()

OLD1 = (
    "    def playlist_name_from_uri(self, uri):\n"
    '        """\n'
    "        Helper function to retrieve the unique MPD playlist name from its URI.\n"
    '        """\n'
    "        if uri not in self._playlist_name_from_uri:\n"
    "            self.refresh_playlists_mapping()\n"
    "        return self._playlist_name_from_uri[uri]\n"
)
NEW1 = (
    "    def playlist_name_from_uri(self, uri):\n"
    '        """\n'
    "        Helper function to retrieve the unique MPD playlist name from its URI.\n"
    "\n"
    "        Returns None if the URI is not (or no longer) a known playlist,\n"
    "        e.g. a transient as_list() failure during the refresh wiped the\n"
    "        cache or the playlist was deleted concurrently.\n"
    '        """\n'
    "        if uri not in self._playlist_name_from_uri:\n"
    "            self.refresh_playlists_mapping()\n"
    "        return self._playlist_name_from_uri.get(uri)\n"
)

if NEW1 in s1:
    print("mpdplaylistnamerace already applied to uri_mapper.py, skip")
else:
    assert s1.count(OLD1) == 1, f"OLD1 count={s1.count(OLD1)}"
    s1 = s1.replace(OLD1, NEW1, 1)
    open(p1, "w").write(s1)
    print(
        "patched uri_mapper.py: playlist_name_from_uri()の素のdictインデックスを"
        ".get()化しKeyErrorを解消 (playlist_uri_from_name()と対称化)"
    )

p2 = "mopidy_mpd/protocol/stored_playlists.py"
s2 = open(p2).read()

OLD2 = (
    "        name = context.lookup_playlist_name_from_uri(playlist_ref.uri)\n"
    '        result.append(("playlist", name))\n'
    '        result.append(("Last-Modified", last_modified))\n'
)
NEW2 = (
    "        name = context.lookup_playlist_name_from_uri(playlist_ref.uri)\n"
    "        if name is None:\n"
    "            continue\n"
    '        result.append(("playlist", name))\n'
    '        result.append(("Last-Modified", last_modified))\n'
)

if NEW2 in s2:
    print("mpdplaylistnamerace already applied to stored_playlists.py, skip")
else:
    assert s2.count(OLD2) == 1, f"OLD2 count={s2.count(OLD2)}"
    s2 = s2.replace(OLD2, NEW2, 1)
    open(p2, "w").write(s2)
    print(
        "patched stored_playlists.py: listplaylists()がuri_mapperからNoneを"
        "受け取った場合そのエントリだけskipするよう修正 "
        "(1件の瞬断でlistplaylists全体・接続が落ちるのを防止)"
    )
