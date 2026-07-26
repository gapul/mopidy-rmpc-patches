# mopidy_ytmusic.backend.py の YTMusicBackend.__init__() は self.api (ytmusicapi
# クライアント) を
#
#     if self.auth and not self.oauth:
#         self.api = YTMusic(auth=self._ytmusicapi_auth_json)
#     elif self.oauth:
#         self.api = YTMusic(auth=self._ytmusicapi_oauth_json)
#     else:
#         self.api = YTMusic()
#
# と self.oauth も正しく分岐条件に含めて生成しているのに対し、
# mopidy_ytmusic.library.py の YTMusicLibraryProvider.browse() は
# self.backend.auth のみで認証済み判定する箇所が4箇所残っている
# (ytoauthplaylistguard-patch.py が backend.py の self.playlists 代入で修正した
# のと全く同型のバグが、browse() 側に横展開されずに残っていた):
#   (1) "ytmusic:root": Home/Artists/Albums ディレクトリそのものの追加
#   (2) "ytmusic:artist": アップロード済みアーティストのマージ
#   (3) "ytmusic:album": アップロード済みアルバムのマージ
#   (4) "ytmusic:watch": 未再生時に履歴から seed track を取得するフォールバック
# auth_json/oauth_json は __init__.py の get_config_schema() で対等な独立の
# optional Path であり、oauth_json のみを設定する構成 (self.auth=False,
# self.oauth=True) では self.api はOAuth認証で正しく生成されるにもかかわらず、
# browse("ytmusic:root") が Home/Artists/Albums/Liked Songs/Recently Played/
# Subscriptions という主要な閲覧用ディレクトリを丸ごと欠落させ(1)、
# ytmusic:artist/ytmusic:album はアップロード曲を含められず(2)(3)、
# ytmusic:watch は同一プロセス内でまだ何も再生していない状態だと履歴から
# 種曲を拾えない(4)。search() は self.auth を見ないため無関係で動くのに
# browse (rmpc等のディレクトリブラウザが使う主経路) だけがこの欠落の影響を
# 受け、エラーも出ずログもクリーンな「静かな」機能欠落になる。
#
# 対策: self.api 初期化・ytoauthplaylistguard-patch.py の self.playlists と
# 同じ条件 (self.auth or self.oauth) へ、browse() 内の4箇所とも統一する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

REPLACEMENTS = [
    (
        '        if uri == "ytmusic:root":\n'
        "            dirs = []\n"
        "            if self.backend.auth:\n",
        '        if uri == "ytmusic:root":\n'
        "            dirs = []\n"
        "            if self.backend.auth or self.backend.oauth:\n",
    ),
    (
        "            except Exception:\n"
        '                logger.exception("YTMusic failed getting artists from library")\n'
        "                library_artists = []\n"
        "            if self.backend.auth:\n",
        "            except Exception:\n"
        '                logger.exception("YTMusic failed getting artists from library")\n'
        "                library_artists = []\n"
        "            if self.backend.auth or self.backend.oauth:\n",
    ),
    (
        "            except Exception:\n"
        '                logger.exception("YTMusic failed getting albums from library")\n'
        "                library_albums = []\n"
        "            if self.backend.auth:\n",
        "            except Exception:\n"
        '                logger.exception("YTMusic failed getting albums from library")\n'
        "                library_albums = []\n"
        "            if self.backend.auth or self.backend.oauth:\n",
    ),
    (
        "                if playback.last_id is not None:\n"
        "                    track_id = playback.last_id\n"
        "                elif self.backend.auth:\n",
        "                if playback.last_id is not None:\n"
        "                    track_id = playback.last_id\n"
        "                elif self.backend.auth or self.backend.oauth:\n",
    ),
]

if all(new in s for _, new in REPLACEMENTS):
    print("library.py already patched (ytoauthlibraryguard), skip")
else:
    for old, new in REPLACEMENTS:
        assert s.count(old) == 1, f"anchor count={s.count(old)} for {old!r}"
        s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: browse()の4箇所(root/artist/album/watch)がself.auth"
        "のみを見てself.oauthを見ておらずoauth_jsonのみ設定時にHome/Artists/"
        "Albums等の主要ブラウズディレクトリが理由不明で消える不具合を修正"
        " (self.api初期化・ytoauthplaylistguard-patch.pyと同じ条件"
        " self.auth or self.oauth へ統一)"
    )
