# mopidy_listenbrainz/listenbrainz.py の validate_token()/submit_listen()/
# list_playlists_created_for_user()/_collect_playlist_data() が、いずれも
# check_response_status(response) (非200応答を自作例外 _RequestError に変換) は
# try/except で握りつぶすようになっている (lb-patch.py/lbplaylistguard-patch.py 適用後) が、
# その手前の `self.session.get()`/`self.session.post()` 自体は try の外側で無防備なまま
# だった不具合。ListenBrainz API が一時的に非200を返す場合 (401/429/5xx等) は
# _RequestError として握りつぶされ既に安全だが、DNS失敗/接続拒否/タイムアウト等の
# ネットワーク層エラーは requests.exceptions.RequestException (ConnectionError/Timeout等)
# として送出され、check_response_status呼び出しより前でraiseされるため誰にも
# 捕捉されず素通りする。
#
# 実害: lbplaylistguard-patch.py/lbmbidguard-patch.py と同根 — (1) validate_token() は
# Listenbrainz.__init__() から同期的に呼ばれ、それは ListenbrainzFrontend.on_start() から
# 呼ばれるため、pykka の ThreadingActor.on_start() 内の未捕捉例外として起動直後に
# actor自体がクラッシュしScrobble含むListenBrainz連携全体がプロセス生涯にわたり
# 無効化される。(2) list_playlists_created_for_user()/_collect_playlist_data() は
# on_start()内の初回import_playlists()、または週次再インポートのthreading.Timer経由の
# 呼び出し中に起きると同様にactorクラッシュ/週次再インポート永久停止を招く。
# (3) submit_listen() (再生の都度呼ばれるscrobble本体) で起きると、1回のネットワーク
# 瞬断のたびに呼び出し元 (ytscrobble-patch.py 等が呼ぶ frontend の on_playback系ハンドラ)
# まで例外が伝播し、mopidyのcore actorへ影響しうる。
# TODO 全項目消化済みのため自走エージェントが Explore サブエージェントに調査を委任し
# 新規発見・追加した項目 (既存の lb-patch.py/lbplaylistguard-patch.py/lbmbidguard-patch.py
# のいずれも check_response_status() のtry/exceptのみを対象にしており、session.get/post()
# 自体を対象にしたパッチは存在しないことを grep で確認した上で着手)。
#
# 修正: 各関数について、既存の `try: check_response_status(response) except
# _RequestError: <既存の戻り値>` を、`self.session.get()/post()` 呼び出しも同じ try に
# 含め、except を `except (requests.exceptions.RequestException, _RequestError):` に
# 拡張する (戻り値は各関数の既存の _RequestError 処理と同一のものを流用するため、
# 呼び出し元から見た正常系の後続処理には影響しない)。
p = "mopidy_listenbrainz/listenbrainz.py"
s = open(p).read()

MARKER = "No playlist created for unknown user"
if MARKER not in s:
    raise AssertionError("MARKER not found: unexpected listenbrainz.py content")

# 1) validate_token()
anchor_validate = (
    "        response = self.session.get(\n"
    "            url=f\"https://{self.url}{VALIDATE_TOKEN_ENDPOINT}\",\n"
    "            headers={\n"
    "                \"Authorization\": f\"Token {self.token}\",\n"
    "            },\n"
    "        )\n"
    "\n"
    "        try:\n"
    "            check_response_status(response)\n"
    "        except _RequestError:\n"
    "            return False\n"
)
replacement_validate = (
    "        try:\n"
    "            response = self.session.get(\n"
    "                url=f\"https://{self.url}{VALIDATE_TOKEN_ENDPOINT}\",\n"
    "                headers={\n"
    "                    \"Authorization\": f\"Token {self.token}\",\n"
    "                },\n"
    "            )\n"
    "            check_response_status(response)\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return False\n"
)

# 2) submit_listen()
anchor_submit = (
    "        response = self.session.post(\n"
    "            # hardcode https?\n"
    "            url=f\"https://{self.url}{SUBMIT_LISTEN_ENDPOINT}\",\n"
    "            json={\n"
    "                \"listen_type\": \"single\" if not now_playing else \"playing_now\",\n"
    "                \"payload\": payload,\n"
    "            },\n"
    "            headers={\n"
    "                \"Authorization\": f\"Token {self.token}\",\n"
    "            },\n"
    "        )\n"
    "        try:\n"
    "            check_response_status(response)\n"
    "        except _RequestError:\n"
    "            pass\n"
)
replacement_submit = (
    "        try:\n"
    "            response = self.session.post(\n"
    "                # hardcode https?\n"
    "                url=f\"https://{self.url}{SUBMIT_LISTEN_ENDPOINT}\",\n"
    "                json={\n"
    "                    \"listen_type\": \"single\" if not now_playing else \"playing_now\",\n"
    "                    \"payload\": payload,\n"
    "                },\n"
    "                headers={\n"
    "                    \"Authorization\": f\"Token {self.token}\",\n"
    "                },\n"
    "            )\n"
    "            check_response_status(response)\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            pass\n"
)

# 3) list_playlists_created_for_user() (lbplaylistguard-patch.py 適用後の形)
anchor_list = (
    "        path = LIST_PLAYLIST_CREATED_FOR_ENDPOINT.format(user=self.user_name)\n"
    "        response = self.session.get(\n"
    "            url=f\"https://{self.url}{path}\",\n"
    "            headers={\n"
    "                \"Authorization\": f\"Token {self.token}\",\n"
    "            },\n"
    "        )\n"
    "        try:\n"
    "            check_response_status(response)\n"
    "        except _RequestError:\n"
    "            return []\n"
)
replacement_list = (
    "        path = LIST_PLAYLIST_CREATED_FOR_ENDPOINT.format(user=self.user_name)\n"
    "        try:\n"
    "            response = self.session.get(\n"
    "                url=f\"https://{self.url}{path}\",\n"
    "                headers={\n"
    "                    \"Authorization\": f\"Token {self.token}\",\n"
    "                },\n"
    "            )\n"
    "            check_response_status(response)\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return []\n"
)

# 4) _collect_playlist_data()
anchor_collect = (
    "        path = PLAYLIST_ENDPOINT.format(playlist_id=playlist_id)\n"
    "        response = self.session.get(\n"
    "            url=f\"https://{self.url}{path}\",\n"
    "            headers={\n"
    "                \"Authorization\": f\"Token {self.token}\",\n"
    "            },\n"
    "        )\n"
    "        try:\n"
    "            check_response_status(response)\n"
    "        except _RequestError:\n"
    "            return None\n"
)
replacement_collect = (
    "        path = PLAYLIST_ENDPOINT.format(playlist_id=playlist_id)\n"
    "        try:\n"
    "            response = self.session.get(\n"
    "                url=f\"https://{self.url}{path}\",\n"
    "                headers={\n"
    "                    \"Authorization\": f\"Token {self.token}\",\n"
    "                },\n"
    "            )\n"
    "            check_response_status(response)\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return None\n"
)

sites = [
    ("validate_token", anchor_validate, replacement_validate),
    ("submit_listen", anchor_submit, replacement_submit),
    ("list_playlists_created_for_user", anchor_list, replacement_list),
    ("_collect_playlist_data", anchor_collect, replacement_collect),
]

already_marker = "except (requests.exceptions.RequestException, _RequestError):"
already_count = s.count(already_marker)

changed = 0
for name, anchor, replacement in sites:
    if anchor not in s:
        if replacement in s:
            print(f"{name}() already guarded against RequestException, skip")
            continue
        raise AssertionError(f"anchor for {name}() not found: unexpected listenbrainz.py content")
    assert s.count(anchor) == 1, f"anchor count for {name}()={s.count(anchor)}"
    s = s.replace(anchor, replacement, 1)
    changed += 1

if changed == 0:
    print("listenbrainz.py already fully guarded against RequestException, skip")
else:
    open(p, "w").write(s)
    print(
        f"patched listenbrainz.py: {changed}箇所の session.get()/post() を "
        "requests.exceptions.RequestException にもガード"
    )
