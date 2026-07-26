# mopidy_listenbrainz/listenbrainz.py の validate_token()/
# list_playlists_created_for_user()/_collect_playlist_data() が、いずれも
# `self.session.get()` 自体のネットワーク層エラー (lbnetguard-patch.py) と
# 非200応答 (_RequestError) は try/except で保護済みだが、その直後の
# `parsed_response = response.json()` は try ブロックの外側で無防備なまま
# だった不具合。
#
# ListenBrainz APIまたは経路上のプロキシ/CDN/ロードバランサが、ステータス200
# (=check_response_status()を素通りする) で本文が空/非JSON (HTMLメンテナンス
# ページ、Cloudflareチャレンジページ、通信打ち切りによる不完全な応答等) を
# 返すと、`response.json()` は `requests.exceptions.JSONDecodeError` を送出する。
# このクラスは `RequestException` のサブクラスではあるが (nix env の python で
# `JSONDecodeError.__mro__` を実行し `InvalidJSONError -> RequestException` の
# 継承を確認済み)、発生箇所が try ブロックの**外側**のため既存の
# `except (requests.exceptions.RequestException, _RequestError):` には一切
# 掛からず素通りする。
#
# 実害: (1) validate_token() は Listenbrainz.__init__() から呼ばれ、それは
# ListenbrainzFrontend.on_start() から同期的に呼ばれるため、pykka の
# ThreadingActor.on_start() 内の未捕捉例外として actor 自体が起動直後に
# クラッシュし ListenBrainz 連携がプロセス生涯にわたり無効化される
# (lbtokennetguard-patch.py が「戻り値の誤判定」経路について解消したのと
# 同じ最終症状を、malformed JSON ボディという別トリガーから再び引き起こす)。
# (2) list_playlists_created_for_user()/_collect_playlist_data() は
# on_start() 内の初回 import_playlists()、または週次再インポートの生の
# threading.Timer コールバック経由で呼ばれるため、同様に actor クラッシュ、
# または (Timer 経由の場合) 例外発生地点が import_playlists() 末尾の
# self._schedule_playlists_import() 呼び出しより前にあるため次回の週次
# タイマーが二度と再スケジュールされない永久停止を招く
# (lbplaylistguard-patch.py/lbnetguard-patch.py が解消したのと同じ症状を
# 同じく別トリガーから再現する)。
# TODO 全項目消化済みのため自走エージェントが general-purpose サブエージェントに
# 調査を委任し新規発見・追加した項目 (既存の lb*-patch.py いずれも
# check_response_status()/session.get()/post() 自体のみを対象にしており、
# その後段の response.json() 呼び出しを対象にしたパッチは存在しないことを
# grep で確認した上で着手)。
#
# 修正: 各関数について、try ブロック内の check_response_status(response) の
# 直後へ `parsed_response = response.json()` を移し、既存の
# `except (requests.exceptions.RequestException, _RequestError):` (JSONDecodeError
# は RequestException のサブクラスのためそのまま捕捉される) に委ねる。戻り値は
# 各関数の既存の失敗時処理と同一のものを流用するため、正常系の後続処理には
# 影響しない。submit_listen() は response.json() を呼ばないため対象外。
p = "mopidy_listenbrainz/listenbrainz.py"
s = open(p).read()

MARKER = "No playlist created for unknown user"
if MARKER not in s:
    raise AssertionError("MARKER not found: unexpected listenbrainz.py content")

# 1) validate_token()
anchor_validate = (
    "            check_response_status(response)\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return None\n"
    "\n"
    "        parsed_response = response.json()\n"
    "        self.user_name = parsed_response.get(\"user_name\")\n"
    "        return parsed_response.get(\"valid\")\n"
)
replacement_validate = (
    "            check_response_status(response)\n"
    "            parsed_response = response.json()\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return None\n"
    "\n"
    "        self.user_name = parsed_response.get(\"user_name\")\n"
    "        return parsed_response.get(\"valid\")\n"
)

# 2) list_playlists_created_for_user()
anchor_list = (
    "            check_response_status(response)\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return []\n"
    "\n"
    "        parsed_response = response.json()\n"
    "        playlists: List[PlaylistData] = []\n"
)
replacement_list = (
    "            check_response_status(response)\n"
    "            parsed_response = response.json()\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return []\n"
    "\n"
    "        playlists: List[PlaylistData] = []\n"
)

# 3) _collect_playlist_data()
anchor_collect = (
    "            check_response_status(response)\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return None\n"
    "\n"
    "        parsed_response = response.json()\n"
    "        dto = parsed_response.get(\"playlist\", {})\n"
)
replacement_collect = (
    "            check_response_status(response)\n"
    "            parsed_response = response.json()\n"
    "        except (requests.exceptions.RequestException, _RequestError):\n"
    "            return None\n"
    "\n"
    "        dto = parsed_response.get(\"playlist\", {})\n"
)

sites = [
    ("validate_token", anchor_validate, replacement_validate),
    ("list_playlists_created_for_user", anchor_list, replacement_list),
    ("_collect_playlist_data", anchor_collect, replacement_collect),
]

changed = 0
for name, anchor, replacement in sites:
    if anchor not in s:
        if replacement in s:
            print(f"{name}() already guards response.json(), skip")
            continue
        raise AssertionError(f"anchor for {name}() not found: unexpected listenbrainz.py content")
    assert s.count(anchor) == 1, f"anchor count for {name}()={s.count(anchor)}"
    s = s.replace(anchor, replacement, 1)
    changed += 1

if changed == 0:
    print("listenbrainz.py already fully guards response.json(), skip")
else:
    open(p, "w").write(s)
    print(
        f"patched listenbrainz.py: {changed}箇所の response.json() を "
        "JSONDecodeError(RequestExceptionのサブクラス)にもガード"
    )
