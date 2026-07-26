# mopidy_ytmusic.library.py の addThumbnails() (self.IMAGES キャッシュへサムネイルURL/
# 解像度を積む共通ヘルパー) が、応答中の各サムネイル要素の "width"/"height" を
# `.get()` ではなく直接インデックス (`th["width"]`, `th["height"]`) で取得しており、
# "url" は持つが "width"/"height" を欠くサムネイル要素 (YouTube側のサムネイル配列に
# 実在する形状) が1つでも含まれていると KeyError を送出する。ytimages-patch.py が
# playlistToTracks() に新設したサムネイルキャッシュ処理では既に `.get()` を使っており
# (同種のリスクを認識した書き方)、addThumbnails() 自体だけがこの防御を欠いていた。
#
# この KeyError は呼び出し元2箇所でいずれも無防備 (try/except で保護されていない) なため
# 深刻な実害になる:
#
# (1) albumToTracks() は全曲を Track に変換し ret に積み終えた後、末尾で
#     `self.addThumbnails(bId, album)` を呼ぶ。ここで KeyError が起きると
#     ytunavailabletrack-patch.py が個々の曲を守る try/except の"外側"で関数全体が
#     中断し `return ret` に到達しないため、既に成功していたN曲分のパース結果ごと
#     失われる。呼び出し元 browse()/lookup() の粗い `except Exception: logger.exception`
#     がこれを飲み込むため、rmpc等のMPDクライアントには「0曲のアルバム」として映る。
#     get_album(bId) は同じデータを毎回返すため一過性ではなく、そのアルバムを開く
#     たびに決定論的に再現する。
#
# (2) getTrack() は `self.TRACKS[bId]` へ書き込んだ直後に
#     `self.addThumbnails(bId, tv["thumbnail"])` を無防備に呼んでおり、ここで
#     KeyError が起きると関数が例外送出し `return self.TRACKS[bId]` に到達しない
#     (呼び出し元 browse()/lookup() 側では「そんな曲は無い」ように見える=addid等が
#     ACK No such song を返す)。かつ self.TRACKS[bId] への書き込み自体は既に完了して
#     いるため、次に同じ bId で getTrack() が呼ばれた際は
#     `if bId not in self.TRACKS:` が False になりブロック全体(addThumbnails呼び出し
#     含む)がスキップされ、2回目の呼び出しだけ正常に返る奇妙な「初回だけ失敗する」
#     挙動になる。
#
# 対策: (a) addThumbnails() 内の width/height 取得を ytimages-patch.py と同じ
# `.get()` に修正 (根本原因)。(b) 加えて呼び出し元2箇所を個別の try/except で囲み、
# サムネイル取得の失敗が既に完成しているトラック一覧/Trackオブジェクトの返却を
# 道連れにしないよう防御する (ytcipherfail-patch.py/ytscrobble-patch.py と同じ
# 「1回限りの外部データ依存呼び出しをtry/exceptで隔離する」流儀)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "YTMusic albumToTracks: failed to add thumbnails"
if MARKER in s:
    print("library.py already patched (ytthumbnailguard), skip")
else:
    # (a) addThumbnails: width/height を .get() に
    OLD_A = '''                if "url" in th:
                    images.append(
                        Image(
                            uri=th["url"],
                            width=th["width"],
                            height=th["height"],
                        )
                    )'''
    NEW_A = '''                if "url" in th:
                    images.append(
                        Image(
                            uri=th["url"],
                            width=th.get("width"),
                            height=th.get("height"),
                        )
                    )'''
    assert s.count(OLD_A) == 1, f"addThumbnails width/height anchor count={s.count(OLD_A)}"
    s = s.replace(OLD_A, NEW_A, 1)

    # (b-1) albumToTracks: 末尾の addThumbnails 呼び出しを try/except で隔離
    OLD_B = '''        self.addThumbnails(bId, album)
        return ret'''
    NEW_B = '''        try:
            self.addThumbnails(bId, album)
        except Exception:
            logger.debug(
                "YTMusic albumToTracks: failed to add thumbnails",
                exc_info=True,
            )
        return ret'''
    assert s.count(OLD_B) == 1, f"albumToTracks addThumbnails anchor count={s.count(OLD_B)}"
    s = s.replace(OLD_B, NEW_B, 1)

    # (b-2) getTrack: addThumbnails 呼び出しを try/except で隔離
    OLD_C = '''            self.addThumbnails(bId, tv["thumbnail"])
        return self.TRACKS[bId]'''
    NEW_C = '''            try:
                self.addThumbnails(bId, tv["thumbnail"])
            except Exception:
                logger.debug(
                    "YTMusic getTrack: failed to add thumbnails",
                    exc_info=True,
                )
        return self.TRACKS[bId]'''
    assert s.count(OLD_C) == 1, f"getTrack addThumbnails anchor count={s.count(OLD_C)}"
    s = s.replace(OLD_C, NEW_C, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: addThumbnails()のwidth/height直接インデックスによる"
        "KeyErrorを.get()化して根本修正し、albumToTracks()/getTrack()末尾の"
        "addThumbnails呼び出しをtry/exceptで隔離して既に完成した結果の道連れ喪失を防止"
    )
