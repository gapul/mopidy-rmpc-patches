# mopidy_listenbrainz/playlists.py の ListenbrainzPlaylistsProvider.save() が、
# uri が "listenbrainz:playlist:recommendation" プレフィックス (ListenBrainz公式が
# 提供する週次の Weekly Jams/Weekly Exploration 等の推薦プレイリスト) の場合にのみ
# 以下のガードを掛けている不具合:
#
#     if not (len(playlist.tracks) > len(found[0].tracks)):
#         # return unchanged playlist for recommendations whose
#         # track list isn't increasing, really save iff first
#         # save after creation or new tracks being available in
#         # Mopidy's database
#         return found[0]
#
# 「新しい曲数が既存より厳密に増えている場合のみ実際に保存し、そうでなければ
# 無変更のまま既存を返す」という判定だが、ListenBrainz の週次推薦プレイリストは
# 曲数がほぼ固定(Weekly Jams/Weekly Exploration ともに毎週50曲)のまま中身(曲)だけ
# 総入れ替えされる運用のため、2週目以降はこの条件がほぼ常に偽になり、
# frontend.py の import_playlists() (_schedule_playlists_import() が
# threading.Timer で毎週自動実行) が新しい週の曲データを渡しても save() は
# 一切反映せず1週目に保存されたプレイリストを無条件でそのまま返し続ける。
# 呼び出し元はこの戻り値が非Noneであることしか見ておらず、ログ上は「保存成功」
# として扱われ例外もエラーログも一切出ないまま、rmpc/mopidy 側に見えるプレイリスト
# の中身は実質的に初回保存時点の曲順のまま恒久的に凍結される (ListenBrainz本家
# では毎週更新されているにもかかわらず気付く手立てが無いサイレントな機能不全)。
#
# 修正: 「曲数が増えているか」ではなく「曲構成(URI列、順序込み)が前回保存時と
# 実際に変わっているか」で判定する。元実装の「無駄な再保存を避ける」という意図
# (コメント "return unchanged playlist for recommendations whose track list
# isn't increasing" から読み取れる、完全に同一の内容を毎週律儀に上書きし続けて
# playlist_changed 相当のイベントを空振りさせない配慮) はそのまま維持しつつ、
# 曲数据え置き/減少の更新を一律で握り潰していた本体のバグだけを解消する。

p = "mopidy_listenbrainz/playlists.py"
s = open(p).read()

OLD = """        if uri.startswith(self.uri_prefix + ":recommendation"):
            if not (len(playlist.tracks) > len(found[0].tracks)):
                # return unchanged playlist for recommendations whose
                # track list isn't increasing, really save iff first
                # save after creation or new tracks being available in
                # Mopidy's database
                return found[0]
"""

NEW = """        if uri.startswith(self.uri_prefix + ":recommendation"):
            new_uris = tuple(t.uri for t in playlist.tracks)
            old_uris = tuple(t.uri for t in found[0].tracks)
            if new_uris == old_uris:
                # 曲構成(URI列、順序込み)が前回保存時と全く同じ場合のみ
                # 無変更のまま返す (lbplaylistrefresh-patch.py: 元実装は曲数の
                # 増減だけを見ており、同数/減少での週次入れ替えを一律で
                # 無視してしまう不具合があった)。
                return found[0]
"""

if NEW in s and OLD not in s:
    print("ListenbrainzPlaylistsProvider.save() already compares track uris, skip")
else:
    count = s.count(OLD)
    assert count == 1, f"OLD count={count}"
    s = s.replace(OLD, NEW)
    open(p, "w").write(s)
    print(
        "patched playlists.py: ListenbrainzPlaylistsProvider.save() が "
        "recommendationプレイリストの曲数据え置き/減少での週次更新を一律で "
        "無視してしまう不具合を修正 (曲数比較→曲構成(URI列)比較へ変更)"
    )
