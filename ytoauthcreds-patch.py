# mopidy-ytmusic の oauth_json 分岐は YTMusic(auth=<oauth.json>) を呼ぶだけだが、
# ytmusicapi 1.x はこの形を OAUTH_CUSTOM_CLIENT と判定し oauth_credentials
# (client_id/client_secret) を必須にしているため、必ず YTMusicUserError で落ちる。
# = oauth_json は現状そのままでは使えない。認証ファイルに一緒に入れておいた
# client_id/client_secret を取り出して OAuthCredentials として渡す。
# ファイルは sops 管理で 0400 (読み取り専用) なので、パスではなく JSON 文字列を渡して
# ytmusicapi にトークンを書き戻させない (更新されたアクセストークンはプロセス内だけで持つ。
# 永続するのは refresh token で、それはこのファイルにある)。
p = "mopidy_ytmusic/backend.py"
s = open(p).read()

if "_ytmusic_from_oauth" not in s:
    helper_anchor = "class YTMusicBackend("
    helper_new = '''def _ytmusic_from_oauth(path):
    import json

    with open(path) as f:
        token = json.load(f)
    client_id = token.pop("client_id", None)
    client_secret = token.pop("client_secret", None)
    if not (client_id and client_secret):
        # client_id を持たない素の oauth.json は従来どおり渡す (ytmusicapi 側で弾かれる)
        return YTMusic(auth=path)
    from ytmusicapi.auth.oauth import OAuthCredentials

    return YTMusic(
        auth=json.dumps(token),
        oauth_credentials=OAuthCredentials(client_id, client_secret),
    )


class YTMusicBackend('''
    assert s.count(helper_anchor) == 1, f"helper anchor count={s.count(helper_anchor)}"
    s = s.replace(helper_anchor, helper_new, 1)

    call_anchor = """        elif self.oauth:
            self.api = YTMusic(auth=self._ytmusicapi_oauth_json)
"""
    call_new = """        elif self.oauth:
            self.api = _ytmusic_from_oauth(self._ytmusicapi_oauth_json)
"""
    assert s.count(call_anchor) == 1, f"call anchor count={s.count(call_anchor)}"
    s = s.replace(call_anchor, call_new, 1)

    open(p, "w").write(s)
    print("patched backend.py: oauth_json に OAuthCredentials を渡す")
else:
    print("_ytmusic_from_oauth already present, skip")
