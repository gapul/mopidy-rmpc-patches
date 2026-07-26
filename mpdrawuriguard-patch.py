# `readcomments {URI}` および `lsinfo {URI}` (曲そのものの生URIへのフォールバック、
# mpdlsinfouri-patch.py) が、docstring/仕様上許容されている「スキーム無しの生パス文字列」
# (例: `readcomments "test.mp3"`、ライブラリに存在しない任意の文字列) を無検証のまま
# `context.core.library.lookup(uris=[uri])` に渡してしまう不具合。TODO 全項目消化済みのため
# 自走エージェントが再調査して新規発見・追加した項目。
#
# mopidy.core.LibraryController.lookup() は内部で
# `mopidy.internal.validation.check_uris()` を呼んでおり、各 URI に対し
# `urllib.parse.urlparse(uri).scheme == ""` なら `mopidy.exceptions.ValidationError`
# (mopidy_mpd 独自の `exceptions.MpdAckError` 系統ではない) を送出する。ソース確認済み。
# `mopidy_mpd/dispatcher.py` の `handle_request()` は `except exceptions.MpdAckError` と
# `except pykka.ActorDeadError` しか捕捉せず、`mopidy_mpd/session.py` の
# `on_line_received()` にも保護が無いため、この `ValidationError` は pykka actor を
# 未捕捉例外のまま突き抜け、当該コネクションが応答無しで即切断される
# (mpdseekcurargerr-patch.py 発見時の素の ValueError によるセッション切断と同種の被害)。
#
# `update`/`rescan` (`_mpdupdate_refresh()`) だけは既にこの `ValidationError` を
# try/except で捕捉し「何もせず正常応答」に変換済みだが、`readcomments` と
# `lsinfo` の生URIフォールバックにはこの防御が一切コピーされていなかった
# (grep で該当箇所を確認)。
#
# 修正方針: `_mpdupdate_refresh()` と同じ変換方針で、
# - `readcomments`: `ValidationError` を「ライブラリに存在しない」と同義に扱い
#   `exceptions.MpdNoExistError("No such song")` に変換 (無効URIも未登録URIも
#   クライアントから見れば同じ「そんな曲は無い」で区別不要なため)。
# - `lsinfo` の生URIフォールバック (`except exceptions.MpdNoExistError:` 節内):
#   `ValidationError` を捕捉した場合はフォールバック自体を諦め、素の `raise`
#   (現在ハンドリング中の元の `MpdNoExistError("Not found")`) を再送出し、
#   ディレクトリが実際に見つからない場合と同じ従来の応答に落とす。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "def _mpd_lookup_uri_or_no_such_song(context, uri):"
if MARKER in s:
    print("music_db.py already patched for raw-uri ValidationError guard, skip")
else:
    old_readcomments = (
        '    """\n'
        "    tracks = context.core.library.lookup(uris=[uri]).get().get(uri) or []\n"
        "    if not tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    comment = tracks[0].comment\n"
    )
    assert s.count(old_readcomments) == 1, (
        f"old_readcomments count={s.count(old_readcomments)}"
    )

    new_readcomments = (
        '    """\n'
        "    tracks = _mpd_lookup_uri_or_no_such_song(context, uri)\n"
        "    if not tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
        "    comment = tracks[0].comment\n"
    )
    s = s.replace(old_readcomments, new_readcomments, 1)

    helper = (
        "def _mpd_lookup_uri_or_no_such_song(context, uri):\n"
        "    import mopidy.exceptions\n"
        "\n"
        "    try:\n"
        "        return context.core.library.lookup(uris=[uri]).get().get(uri) or []\n"
        "    except mopidy.exceptions.ValidationError:\n"
        "        # uri がスキーム無し (実MPD流の素のパス等) で mopidy の URI 形式として\n"
        "        # 不正な場合。_mpdupdate_refresh と同じ扱いで「そんな曲は無い」に丸める。\n"
        "        return []\n"
        "\n"
        "\n"
        '@protocol.commands.add("readcomments")'
    )
    old_anchor = '@protocol.commands.add("readcomments")'
    assert s.count(old_anchor) == 1, f"old_anchor count={s.count(old_anchor)}"
    s = s.replace(old_anchor, helper, 1)

    old_lsinfo_fallback = (
        "        if uri is None:\n"
        "            raise\n"
        "        tracks = context.core.library.lookup(uris=[uri]).get().get(uri) or []\n"
        "        if not tracks:\n"
        "            raise\n"
    )
    assert s.count(old_lsinfo_fallback) == 1, (
        f"old_lsinfo_fallback count={s.count(old_lsinfo_fallback)}"
    )
    new_lsinfo_fallback = (
        "        if uri is None:\n"
        "            raise\n"
        "        tracks = _mpd_lookup_uri_or_no_such_song(context, uri)\n"
        "        if not tracks:\n"
        "            raise\n"
    )
    s = s.replace(old_lsinfo_fallback, new_lsinfo_fallback, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: readcomments/lsinfo の生URIフォールバックが "
        "core.library.lookup() の ValidationError (スキーム無しURI) で未捕捉のまま "
        "セッションを切断してしまう不具合を修正 (共通ヘルパで捕捉し空扱いに変換)"
    )
