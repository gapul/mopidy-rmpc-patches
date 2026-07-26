# mopidy_listenbrainz/frontend.py の ListenbrainzFrontend._collect_playlist_tracks()
# 内で呼ぶ musicbrainzngs.get_recording_by_id() (MusicBrainz本家APIへのネットワーク呼び出し)
# だけが無防備で、MusicBrainz APIが一時的にエラー (レート制限/5xx/ネットワーク断等) を
# 返すと musicbrainzngs.WebServiceError (NetworkError/ResponseError/AuthenticationErrorの
# 親クラス) がそのまま呼び出し元 import_playlists() まで素通りする不具合。
#
# lbplaylistguard-patch.py が同じ import_playlists() 呼び出し経路にある
# Listenbrainz.list_playlists_created_for_user() (ListenBrainz本家APIの _RequestError) を
# 既に同種のパターンで修正済みだが、この関数だけはローカルライブラリ検索で見つからなかった
# 曲を MusicBrainz 本家APIから補完しようとする別の外部API呼び出しであり、ガードが漏れていた。
#
# 実害: (1) on_start() 内の初回 import_playlists() 呼び出し中にこれが起きると、pykka の
# ThreadingActor.on_start() 内の未捕捉例外として actor 自体がクラッシュし、ListenBrainz
# 連携(scrobble含む)全体がプロセス生涯にわたり無効化される。
# (2) 週次再インポートの threading.Timer 経由の呼び出し中に発生すると、
# import_playlists() が例外で中断し末尾の self._schedule_playlists_import() に
# 到達しないため、次回の週次インポートが二度とスケジュールされなくなる
# (Timer スレッドが黙って死ぬだけでログにも次回予定が残らない)。
#
# 修正: get_recording_by_id() を try/except musicbrainzngs.WebServiceError で囲み、
# 失敗時は mb_recording_query = None として扱う。これは既存コードが
# 「if mb_recording_query and mb_recording_query["recording"]:」で判定している
# 「MusicBrainzに情報が無かった」場合と同じ経路を通るため、その曲だけ
# found_tracks が空のままスキップされ (呼び出し元の `if len(found_tracks) == 0: continue`)、
# import_playlists() 全体は正常終了まで到達する。
p = "mopidy_listenbrainz/frontend.py"
s = open(p).read()

anchor = (
    "            if len(found_tracks) == 0:\n"
    "                # retrieve track information from MB\n"
    "                mb_recording_query = musicbrainzngs.get_recording_by_id(\n"
    "                    track_mbid, includes=[\"artists\"]\n"
    "                )\n"
    "                if mb_recording_query and mb_recording_query[\"recording\"]:\n"
)

if anchor not in s:
    if "except musicbrainzngs.WebServiceError:" in s:
        print("_collect_playlist_tracks() already guarded, skip")
    else:
        raise AssertionError("anchor not found: unexpected frontend.py content")
else:
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    replacement = anchor.replace(
        "                mb_recording_query = musicbrainzngs.get_recording_by_id(\n"
        "                    track_mbid, includes=[\"artists\"]\n"
        "                )\n",
        "                try:\n"
        "                    mb_recording_query = musicbrainzngs.get_recording_by_id(\n"
        "                        track_mbid, includes=[\"artists\"]\n"
        "                    )\n"
        "                except musicbrainzngs.WebServiceError:\n"
        "                    mb_recording_query = None\n",
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print(
        "patched frontend.py: _collect_playlist_tracks() の "
        "musicbrainzngs.get_recording_by_id() を try/except musicbrainzngs.WebServiceError でガード"
    )
