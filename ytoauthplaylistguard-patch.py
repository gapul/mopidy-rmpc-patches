# mopidy_ytmusic.backend.py の YTMusicBackend.__init__() で、self.api (ytmusicapi
# クライアント) の初期化は
#
#     if self.auth and not self.oauth:
#         self.api = YTMusic(auth=self._ytmusicapi_auth_json)
#     elif self.oauth:
#         self.api = YTMusic(auth=self._ytmusicapi_oauth_json)
#     else:
#         self.api = YTMusic()
#
# と self.oauth を正しく分岐条件に含めているのに対し、直後の self.playlists 代入
#
#     if self.auth:
#         self.playlists = YTMusicPlaylistsProvider(backend=self)
#
# は self.auth のみで判定し self.oauth を見ていない。self.auth/self.oauth は
# config["ytmusic"]["auth_json"]/["oauth_json"] がそれぞれ設定されているかで独立に
# 立つフラグ (__init__.py の get_config_schema() で両方とも対等な optional Path)
# なので、oauth_json のみを設定し auth_json を空にする構成 (self.auth=False,
# self.oauth=True) では self.api はOAuth認証で正しく生成されるにもかかわらず
# self.playlists は一度も代入されず、mopidy.backend.Backend のクラス属性デフォルト
# playlists=None のままになる。結果 has_playlists() が False を返し mopidy core が
# このバックエンドを playlists プロバイダ集合から除外するため、MPD の
# listplaylists/load/playlistadd/rm/rename (mopidy_mpd/protocol/stored_playlists.py)
# がYouTube Musicのプレイリストを完全に無視する「静かな」機能欠落になる
# (エラーは出ない、ログもクリーン)。
#
# 対策: self.api 初期化と同じ条件 (self.auth or self.oauth) にする。
p = "mopidy_ytmusic/backend.py"
s = open(p).read()

OLD = (
    '        self.playback = YTMusicPlaybackProvider(audio=audio, backend=self)\n'
    '        self.library = YTMusicLibraryProvider(backend=self)\n'
    '        if self.auth:\n'
    '            self.playlists = YTMusicPlaylistsProvider(backend=self)\n'
)
NEW = (
    '        self.playback = YTMusicPlaybackProvider(audio=audio, backend=self)\n'
    '        self.library = YTMusicLibraryProvider(backend=self)\n'
    '        if self.auth or self.oauth:\n'
    '            self.playlists = YTMusicPlaylistsProvider(backend=self)\n'
)

if NEW in s:
    print("backend.py already patched (ytoauthplaylistguard), skip")
else:
    assert s.count(OLD) == 1, f"playlists guard anchor count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched backend.py: __init__()のself.playlists代入がself.authのみを見て"
        "self.oauthを見ておらずoauth_jsonのみ設定時にYouTube Musicプレイリスト機能"
        "全体(has_playlists()=False)が理由不明で消える不具合を修正"
        " (self.api初期化と同じ条件 self.auth or self.oauth へ統一)"
    )
