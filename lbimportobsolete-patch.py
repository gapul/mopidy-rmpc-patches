# mopidy_listenbrainz/frontend.py の ListenbrainzFrontend.import_playlists() が、
# 「今回 ListenBrainz 側にまだ存在することが確認できたローカルの recommendation
# プレイリスト」を誤って削除しうる不具合。
#
# import_playlists() は既存のローカル "listenbrainz:playlist:recommendation:*" を
# filtered_existing_playlists に集めておき、list_playlists_created_for_user() が
# 返す playlist_datas をループしながら「今回もLB側に存在が確認できたもの」だけ
# filtered_existing_playlists から pop() して削除対象から除外し、ループ後に
# 残ったものだけを obsolete として self.playlists.delete() する設計:
#
#     tracks = self._collect_playlist_tracks(playlist_data)
#
#     if len(tracks) == 0:
#         logger.debug(...)
#         continue                       # <- pop() より先に continue してしまう
#
#     if playlist_uri in filtered_existing_playlists:
#         filtered_existing_playlists.pop(playlist_uri)
#         ...
#
# _collect_playlist_data()(listenbrainz.py)は track_mbids が空のプレイリストを
# 既に playlist_datas から除外済みなので、import_playlists() 側で tracks が
# 0件になるのは「LB側にプレイリストが無い」からではなく、_collect_playlist_tracks()
# 内のローカルライブラリ検索とMusicBrainzフォールバック検索が(一時的なネットワーク
# 不調・ライブラリ再インデックス中等で)その回だけ全滅した結果でしかない。
# つまり「LB側にはまだ存在するのに曲解決だけ失敗した」プレイリストが、tracks==0の
# continue でpop()に到達できないままfiltered_existing_playlistsに残存し、ループ後の
# obsolete削除ループに巻き込まれて誤って削除される(=まだ有効なプレイリストの
# サイレントなデータ消失)。
#
# 修正: 「LB側に存在するかどうか」の判定(pop())を tracks==0 の continue より
# 前に移動する。LB側に存在することが確認できた時点で無条件にpopして削除対象から
# 外し、曲解決に失敗した回はsave/create自体はスキップして前回保存済みの内容を
# そのまま温存する。

p = "mopidy_listenbrainz/frontend.py"
s = open(p).read()

OLD = """            tracks = self._collect_playlist_tracks(playlist_data)

            if len(tracks) == 0:
                logger.debug(
                    f"Skipping import of playlist with no known track for {source!r}"
                )
                continue

            if playlist_uri in filtered_existing_playlists:
                filtered_existing_playlists.pop(playlist_uri)
                # must pop since filtered_existing_playlists will
                # finally be deleted

                logger.debug(f"Already known playlist {playlist_uri}")
                # maybe there're new tracks in Mopidy's database...
            else:
"""

NEW = """            tracks = self._collect_playlist_tracks(playlist_data)

            already_known = playlist_uri in filtered_existing_playlists
            if already_known:
                filtered_existing_playlists.pop(playlist_uri)
                # must pop as soon as we know ListenBrainz still reports this
                # playlist, *before* the tracks==0 check below: LB still has
                # it, so it must never be treated as obsolete just because
                # this round's track resolution (local search + MusicBrainz
                # fallback) failed for every track (lbimportobsolete-patch.py)

                logger.debug(f"Already known playlist {playlist_uri}")
                # maybe there're new tracks in Mopidy's database...

            if len(tracks) == 0:
                logger.debug(
                    f"Skipping import of playlist with no known track for {source!r}"
                )
                continue

            if not already_known:
"""

if NEW in s and OLD not in s:
    print("ListenbrainzFrontend.import_playlists() already pops before the tracks==0 check, skip")
else:
    count = s.count(OLD)
    assert count == 1, f"OLD count={count}"
    s = s.replace(OLD, NEW)
    open(p, "w").write(s)
    print(
        "patched frontend.py: import_playlists() がLB側にまだ存在するのに"
        "曲解決だけ失敗したrecommendationプレイリストを誤ってobsolete削除して"
        "しまう不具合を修正 (既存判定のpop()をtracks==0チェックより前に移動)"
    )
