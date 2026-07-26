# mopidy_listenbrainz/listenbrainz.py の Listenbrainz.__init__() が、
# validate_token() の戻り値 False を「トークンが本当に無効 (200応答の
# valid:false)」と「一時的なネットワーク層エラー (DNS失敗/接続拒否/タイムアウト等の
# requests.exceptions.RequestException、または非200応答の _RequestError)」の
# 両方で区別せず、いずれも同じ `raise RuntimeError(f"Token {token} is not valid")`
# へ変換してしまう不具合。lbnetguard-patch.py が validate_token() 自体を
# RequestException にも安全化した (session.get()自体の例外を握りつぶし False を返す)
# ため、check_response_status()/session.get() が例外を送出しなくなった旨は
# 正しいが、その「例外が起きた」という事実が呼び出し元の __init__() には一切
# 伝わらず、ただの bool False としてしか見えないため、__init__() 側の
# `if not self.validate_token(): raise RuntimeError(...)` は今もなお発火する。
#
# 実害: mopidy 起動時 (ListenbrainzFrontend.on_start() から Listenbrainz(...)
# を同期構築する経路) に ListenBrainz API へ一時的に到達できない状態
# (起動直後でDNSがまだ安定していない、API側の瞬断、リモートAPIのレート制限/5xx等)
# だと、validate_token() は lbnetguard-patch.py のガードにより例外を送出せず
# 静かに False を返すが、__init__() はこれを「トークン無効」と誤解して
# RuntimeError を新たに送出する。これは pykka の
# ThreadingActor._actor_loop_setup() 内の on_start() 未捕捉例外として
# actor 自体を停止させ、ListenBrainz 連携 (scrobble含む) がプロセス生涯に
# わたり無効化されてしまう — lbplaylistguard-patch.py/lbmbidguard-patch.py/
# lbnetguard-patch.py が繰り返し解消してきたのと全く同じ「actor起動時クラッシュ」
# 症状が、validate_token() 自体をガードしたことで一段深いこの箇所に移動しただけで
# 残っていた形。
# TODO 全項目消化済みのため自走エージェントが Explore サブエージェントに調査を
# 委任し新規発見・追加した項目 (lbnetguard-patch.py はあくまで
# validate_token()/submit_listen()/list_playlists_created_for_user()/
# _collect_playlist_data() の session.get()/post() 自体を対象にしており、
# __init__() の `raise RuntimeError` 行自体は grep で確認した限りいずれの
# lb*-patch.py からも触れられていないことを確認した上で着手)。
#
# 修正: validate_token() の戻り値を bool から Optional[bool] へ拡張し、
# 例外 (RequestException/_RequestError) 発生時は「無効と判定できた」False では
# なく「判定不能」を表す None を返すようにする (実際にトークンが不正な場合は
# 従来通りサーバーから200応答の valid:false が返り False のまま維持されるため、
# その回帰は無い)。__init__() 側は None のときは RuntimeError を送出せず
# warning ログのみで起動を継続する (submit_listen()等は各呼び出し単位で
# 既に RequestException を自己防御済みのため、以後のAPI呼び出しは接続が
# 回復し次第自然に成功するようになる。False (本当に無効) のときのみ
# 従来通り RuntimeError で fail-fast する)。
p = "mopidy_listenbrainz/listenbrainz.py"
s = open(p).read()

MARKER = "No playlist created for unknown user"
if MARKER not in s:
    raise AssertionError("MARKER not found: unexpected listenbrainz.py content")

anchor_init = (
    '        if not self.validate_token():\n'
    '            raise RuntimeError(f"Token {token} is not valid")\n'
)
replacement_init = (
    '        token_valid = self.validate_token()\n'
    '        if token_valid is None:\n'
    '            logger.warning(\n'
    '                "Could not validate Listenbrainz token due to a network "\n'
    '                "error; proceeding without validation, ListenBrainz "\n'
    '                "features will keep retrying once connectivity is restored"\n'
    '            )\n'
    '        elif not token_valid:\n'
    '            raise RuntimeError(f"Token {token} is not valid")\n'
)

anchor_validate = (
    '    def validate_token(self) -> bool:\n'
    '        try:\n'
    '            response = self.session.get(\n'
    '                url=f"https://{self.url}{VALIDATE_TOKEN_ENDPOINT}",\n'
    '                headers={\n'
    '                    "Authorization": f"Token {self.token}",\n'
    '                },\n'
    '            )\n'
    '            check_response_status(response)\n'
    '        except (requests.exceptions.RequestException, _RequestError):\n'
    '            return False\n'
)
replacement_validate = (
    '    def validate_token(self) -> Optional[bool]:\n'
    '        try:\n'
    '            response = self.session.get(\n'
    '                url=f"https://{self.url}{VALIDATE_TOKEN_ENDPOINT}",\n'
    '                headers={\n'
    '                    "Authorization": f"Token {self.token}",\n'
    '                },\n'
    '            )\n'
    '            check_response_status(response)\n'
    '        except (requests.exceptions.RequestException, _RequestError):\n'
    '            return None\n'
)

changed = 0

if anchor_init not in s:
    if replacement_init in s:
        print("Listenbrainz.__init__() already distinguishes network-error from invalid token, skip")
    else:
        raise AssertionError("anchor for __init__() not found: unexpected listenbrainz.py content")
else:
    assert s.count(anchor_init) == 1, f"anchor count for __init__()={s.count(anchor_init)}"
    s = s.replace(anchor_init, replacement_init, 1)
    changed += 1

if anchor_validate not in s:
    if replacement_validate in s:
        print("validate_token() already returns Optional[bool], skip")
    else:
        raise AssertionError("anchor for validate_token() not found: unexpected listenbrainz.py content")
else:
    assert s.count(anchor_validate) == 1, f"anchor count for validate_token()={s.count(anchor_validate)}"
    s = s.replace(anchor_validate, replacement_validate, 1)
    changed += 1

if changed == 0:
    print("listenbrainz.py already patched for token-vs-network distinction, skip")
else:
    open(p, "w").write(s)
    print(
        f"patched listenbrainz.py: {changed}箇所 (validate_token()の戻り値をOptional[bool]化、"
        "__init__()のネットワークエラー誤判定をwarningへ緩和)"
    )
