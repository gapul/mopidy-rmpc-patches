# library.py の browse() `ytmusic:artist:<id>:upload` (アップロード済みアーティスト)
# 分岐が、`uploadArtistToTracks(res)` で曲一覧を正しく変換し終えた直後の
# デバッグログで `res[0]["artist"][0]["name"]` という存在しないキー ("artist",
# 単数) にアクセスし KeyError を送出する不具合。
#
# get_library_upload_artist() (ytmusicapi) が返す生トラック辞書のアーティスト
# フィールドは "artists" (複数・list) であり "artist" (単数) ではない。これは
# uploadArtistToTracks() 自身の実装 (`for a in track.get("artists") or []:`)
# からも明らか。
#
# tracks = self.uploadArtistToTracks(res) の時点で変換は既に成功しているにも
# 関わらず、その直後の logger.debug() 行で KeyError が起き、直後の
# `except Exception: logger.exception(...)` に握り潰されて return 文まで
# 到達できない。結果として browse() はこの分岐の末尾 (return なし →
# 呼び出し元の browse() 全体が最終的に空リストへフォールスルー) になり、
# rmpc で「YouTube Music」→ Uploads のアーティスト別ブラウズが、
# アップロード曲を持つアカウントでは常に空フォルダに見える
# (曲は一歩手前まで正しく変換されていたのに、無関係なログ出力の
# タイポで握り潰される「静かな」不具合)。
#
# 対策: キー名を "artists" (複数) に修正し、res が空 / res[0] に "artists" が
# 無い / artists が空リストの場合にも IndexError/KeyError を起こさないよう
# フォールバックを入れる (bId をログへ使う)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'res[0]["artists"][0]["name"]'
if MARKER in s:
    print("library.py already patched (ytuploadartistbrowselog), skip")
else:
    OLD = '''                    res = self.backend.api.get_library_upload_artist(bId)
                    tracks = self.uploadArtistToTracks(res)
                    logger.debug(
                        'YTMusic found %d songs for uploaded artist "%s"',
                        len(res),
                        res[0]["artist"][0]["name"],
                    )
                    return [Ref.track(uri=t.uri, name=t.name) for t in tracks]'''
    NEW = '''                    res = self.backend.api.get_library_upload_artist(bId)
                    tracks = self.uploadArtistToTracks(res)
                    logger.debug(
                        'YTMusic found %d songs for uploaded artist "%s"',
                        len(res),
                        res[0]["artists"][0]["name"]
                        if res and res[0].get("artists")
                        else bId,
                    )
                    return [Ref.track(uri=t.uri, name=t.name) for t in tracks]'''
    assert s.count(OLD) == 1, (
        f"expected 1 occurrence of browse() upload-artist debug-log anchor (got {s.count(OLD)})"
    )
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: browse() ytmusic:artist:<id>:upload分岐のデバッグログが"
        "存在しないキー'artist'(正しくは'artists')にアクセスしKeyErrorでtracksを"
        "握り潰し常に空ブラウズになる不具合を修正"
    )
