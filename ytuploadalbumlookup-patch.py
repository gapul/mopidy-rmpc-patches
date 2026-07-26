# mopidy_ytmusic.library.py の lookup() (add/findadd/playlistadd 等、core.library.lookup()
# 経由で呼ばれる唯一の変換経路) が、アップロード済みアルバム (ytmusic:album:<id>:upload)
# に対してだけ誤った変換関数 albumToTracks() を呼ぶ不具合。
#
# 同じ URI (ytmusic:album:<id>:upload) を browse() (478-479行目) で辿ると
# get_library_upload_album(bId) の戻り値を uploadAlbumToTracks(res, bId) に渡して
# 正しい :upload 付き Album/Artist URI で曲一覧を組み立てるのに、lookup() だけ
# albumToTracks(res, bId) (非アップロード専用、get_album() の戻り値用) を呼んでいる。
#
# get_library_upload_album() の戻り値は uploadAlbumToTracks() 用のデータ構造であり、
# それを albumToTracks() に渡すと:
# - self.ALBUMS[bId] が `ytmusic:album:{bId}` (:upload 無し) という、実際には解決不能な
#   URI で上書きされる。browse() が先に同じ bId を正しい :upload 付きで登録していても、
#   後から lookup() が実行されるとサイレントに誤ったURIで上書きされてしまう
#   (self.ALBUMS は upload/非upload を区別しない共有dict)。
# - album["tracks"] を無条件添字アクセスするため (uploadAlbumToTracks() は
#   `if "tracks" in album:` でガード済み)、get_library_upload_album() の戻り値の形が
#   想定と違えば KeyError で lookup() 全体が失敗し0曲になる。
# - 曲自体が生成できたケースでも、Album/Artist の uri が :upload を欠いた無効な参照になり
#   album アートワーク取得等の後続処理がサイレントに空を返す。
#
# 実害: YTMusic の「アップロード済み楽曲」ライブラリを持つアカウントで、browse() で
# 辿った ytmusic:album:<id>:upload を add/findadd/playlistadd すると、Trackのalbum.uriが
# 不正 (:upload 欠落) になりアルバムアートが取れなくなる、または0曲判定になる。
# 全く同じバグクラスのアーティスト版が ytuploadartistlookup-patch.py で既に修正済みだが
# (「browse()と対称に…」)、すぐ上にある album 分岐の同型バグが見落とされたまま残っていた。
#
# 対策: browse() と対称に、lookup() のアップロードアルバム分岐も
# uploadAlbumToTracks(res, bId) を呼ぶよう修正する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "lookup()のアップロードアルバム分岐はuploadAlbumToTracks"
if MARKER in s:
    print("library.py already patched (ytuploadalbumlookup), skip")
else:
    OLD = '''        if upload:
            if uri.startswith("ytmusic:album:"):
                try:
                    res = self.backend.api.get_library_upload_album(bId)
                    tracks = self.albumToTracks(res, bId)
                    return tracks
                except Exception:
                    logger.exception(
                        'YTMusic failed getting tracks for album "%s"', bId
                    )'''
    NEW = '''        if upload:
            if uri.startswith("ytmusic:album:"):
                try:
                    # lookup()のアップロードアルバム分岐はuploadAlbumToTracks()を
                    # 使う (get_library_upload_album()はuploadAlbumToTracks()専用の
                    # データ構造を返すため、非アップロード専用のalbumToTracks()を渡すと
                    # :upload無しの無効なAlbum/Artist URIで上書きされる。browse()と対称)。
                    res = self.backend.api.get_library_upload_album(bId)
                    tracks = self.uploadAlbumToTracks(res, bId)
                    return tracks
                except Exception:
                    logger.exception(
                        'YTMusic failed getting tracks for album "%s"', bId
                    )'''
    assert s.count(OLD) == 1, (
        f"expected 1 occurrence of lookup() upload-album anchor (got {s.count(OLD)})"
    )
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: lookup()のアップロードアルバム分岐がalbumToTracks()"
        "(非アップロード専用)を誤って呼びAlbum/Artist URIの:upload欠落・0曲判定を"
        "招く不具合を修正 (uploadAlbumToTracks()に変更、browse()と対称化)"
    )
