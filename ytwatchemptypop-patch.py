# mopidy_ytmusic.library.py の browse() "ytmusic:watch" (Similar to last played)
# 分岐が、get_watch_playlist() の返す res["tracks"] が空リスト (キー自体は存在するが
# 曲が0件、例えば直近曲がラジオ候補を生成できないタイプの動画の場合) のとき、
# 先頭のシード曲を捨てるための res["tracks"].pop(0) を無条件に呼んでおり IndexError を
# 送出する不具合を修正する。
#
# 同じ関数の2行上、hist[0]["videoId"] (履歴が空リストの場合の同種の未ガードアクセス)
# は ythistory-patch.py で既に "if hist else None" とガード済みだが、その2行下に
# ある res["tracks"].pop(0) は同じ「空リストへの無条件アクセス」パターンにも関わらず
# 見落とされたまま残っていた。
#
# 例外は呼び出し元の try/except (browse()内) で捕捉されるため MPD セッションは
# 落ちないが、mopidy.log に不要な ERROR Traceback ("YTMusic failed getting watch
# songs") が残り、rmpc の「Similar to last played」フォルダが常に空表示になる。
# pop(0) を空チェックで包み、空なら何もしないことで例外を防ぎ (以後
# playlistToTracks(res) は空リストのまま実行され、これまで通り空のトラック一覧を
# 返す=機能的な回帰なし)、無用なエラーログのみを解消する。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

OLD = '''                        res["tracks"].pop(0)
                        tracks = self.playlistToTracks(res)'''
NEW = '''                        if res["tracks"]:
                            res["tracks"].pop(0)
                        tracks = self.playlistToTracks(res)'''

if "if res[\"tracks\"]:\n                            res[\"tracks\"].pop(0)" in s:
    print("library.py already patched (watch empty pop guard), skip")
else:
    assert s.count(OLD) == 1, f"expected 1 occurrence of watch pop(0) anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: ytmusic:watch分岐のres[\"tracks\"].pop(0)が空リストで"
        "IndexErrorを送出する不具合を修正"
    )
