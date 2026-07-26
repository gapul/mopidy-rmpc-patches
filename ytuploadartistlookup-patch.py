# mopidy_ytmusic.library.py の lookup() (add/findadd/playlistadd 等、core.library.lookup()
# 経由で呼ばれる唯一の変換経路) が、アップロード済みアーティスト (ytmusic:artist:<id>:upload)
# に対してだけ誤った変換関数 artistToTracks() を呼び、常に失敗して0曲を返す不具合。
#
# 同じ URI (ytmusic:artist:<id>:upload) を browse() (446-448行目) で辿ると
# get_library_upload_artist(bId) の戻り値を uploadArtistToTracks(res) に渡して正しく
# 曲一覧を得られるのに、lookup() だけ artistToTracks(res) を呼んでいる。
#
# get_library_upload_artist() (ytmusicapi) は生トラック辞書の list を返す。
# - uploadArtistToTracks(artist): `for track in artist:` と list を前提に書かれている
#   (uploadAlbumToTracks/uploadArtistToTracks 系統、実際に upload API の戻り値を食う関数)。
# - artistToTracks(artist): `artist.get("songs")` と dict を前提に書かれている
#   (get_artist() の戻り値専用、非アップロード経路 browse()/lookup() の else 節で使う関数)。
# list に .get は無いため、lookup() のアップロードアーティスト分岐は必ず
# AttributeError: 'list' object has no attribute 'get' を起こし、直後の
# `except Exception: logger.exception(...)` に握り潰される。その後 lookup() 末尾の
# フォールバック (`if bId in self.TRACKS: ... else: return [self.getTrack(bId)]`) が
# アーティストの browseId をトラックIDとして getTrack() に渡してしまい、さらに壊れた
# 結果 (曲名がアーティスト名になる/例外) を招く。
#
# 実害: YTMusic の「アップロード済み楽曲」ライブラリを持つアカウントで、
# browse() で辿った ytmusic:artist:<id>:upload を add/findadd/playlistadd すると、
# browse 一覧では曲が見えているのに追加すると常に0曲になる (エラー表示もされず
# 静かに失敗する)。
#
# 対策: browse() と対称に、lookup() のアップロードアーティスト分岐も
# uploadArtistToTracks(res) を呼ぶよう修正する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "lookup()のアップロードアーティスト分岐はuploadArtistToTracks"
if MARKER in s:
    print("library.py already patched (ytuploadartistlookup), skip")
else:
    OLD = '''            elif uri.startswith("ytmusic:artist:"):
                try:
                    res = self.backend.api.get_library_upload_artist(bId)
                    tracks = self.artistToTracks(res)
                    return tracks
                except Exception:
                    logger.exception(
                        'YTMusic failed getting tracks for artist "%s"', bId
                    )
        else:'''
    NEW = '''            elif uri.startswith("ytmusic:artist:"):
                try:
                    # lookup()のアップロードアーティスト分岐はuploadArtistToTracks()を
                    # 使う (get_library_upload_artist()はlistを返すため、dict前提の
                    # artistToTracks()を渡すと必ずAttributeErrorになる。browse()と対称)。
                    res = self.backend.api.get_library_upload_artist(bId)
                    tracks = self.uploadArtistToTracks(res)
                    return tracks
                except Exception:
                    logger.exception(
                        'YTMusic failed getting tracks for artist "%s"', bId
                    )
        else:'''
    assert s.count(OLD) == 1, (
        f"expected 1 occurrence of lookup() upload-artist anchor (got {s.count(OLD)})"
    )
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: lookup()のアップロードアーティスト分岐がartistToTracks()"
        "(dict前提)を誤って呼びAttributeErrorで0曲になる不具合を修正 "
        "(uploadArtistToTracks()に変更、browse()と対称化)"
    )
