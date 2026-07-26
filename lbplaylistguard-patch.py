# mopidy_listenbrainz/listenbrainz.py の Listenbrainz.list_playlists_created_for_user()
# だけが check_response_status(response) を try/except で囲んでいない不具合。
# 同ファイルの validate_token()/submit_listen()/_collect_playlist_data() はいずれも
# check_response_status() (非200で自作例外 _RequestError を送出) を
# `try: ... except _RequestError: ...` で握りつぶしているのに対し、この関数だけ
# 無防備なため、ListenBrainz API が一時的に非200 (401/429/5xx等) を返すと
# _RequestError がそのまま呼び出し元 frontend.py の ListenbrainzFrontend まで素通りする。
#
# 実害: (1) on_start() 内の最初の import_playlists() 呼び出し中にこれが起きると、
# pykka の ThreadingActor.on_start() 内の未捕捉例外として actor 自体がクラッシュし、
# ListenBrainz 連携全体(scrobble含む)がプロセス生涯にわたり無効化される。
# (2) 週次再インポートの threading.Timer 経由の呼び出しで起きた場合、
# import_playlists() が例外で中断し末尾の self._schedule_playlists_import() に
# 到達しないため、次回の週次インポートが二度とスケジュールされなくなる
# (Timer 実行スレッドが黙って死ぬだけでログにも次回予定が残らない)。
# TODO 全項目消化済みのため自走エージェントが Explore サブエージェントに調査を
# 委任し新規発見・追加した項目 (lb-patch.py は submit_listen() の空 release_name
# のみが対象で本件とは無関係であることを確認した上で着手)。
#
# 修正: validate_token() と同じ流儀で try/except _RequestError: return [] を追加する。
# これにより一時的なAPIエラーでは空リストとして扱われ import_playlists() は正常終了まで
# 到達するため、(1) actor クラッシュも (2) 週次再スケジュール停止も同時に解消する。
p = "mopidy_listenbrainz/listenbrainz.py"
s = open(p).read()

MARKER = "No playlist created for unknown user"
anchor = (
    "        path = LIST_PLAYLIST_CREATED_FOR_ENDPOINT.format(user=self.user_name)\n"
    "        response = self.session.get(\n"
    "            url=f\"https://{self.url}{path}\",\n"
    "            headers={\n"
    "                \"Authorization\": f\"Token {self.token}\",\n"
    "            },\n"
    "        )\n"
    "        check_response_status(response)\n"
)

if MARKER not in s:
    raise AssertionError("MARKER not found: unexpected listenbrainz.py content")

if anchor not in s:
    print("list_playlists_created_for_user() already guarded, skip")
else:
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    replacement = anchor.replace(
        "        check_response_status(response)\n",
        "        try:\n"
        "            check_response_status(response)\n"
        "        except _RequestError:\n"
        "            return []\n",
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print(
        "patched listenbrainz.py: list_playlists_created_for_user() の "
        "check_response_status() を try/except _RequestError: return [] でガード"
    )
