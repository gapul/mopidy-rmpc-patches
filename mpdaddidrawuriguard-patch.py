# `addid {URI}` (mopidy_mpd/protocol/current_playlist.py) と
# `playlistadd {NAME} {URI}` (mopidy_mpd/protocol/stored_playlists.py) が、
# 兄弟コマンド `add {URI}` とは異なり、docstring/仕様上許容されている
# 「スキーム無しの生パス文字列」(例: `addid "foo.mp3"`、ライブラリ相対パス) を
# 無検証のまま `context.core.tracklist.add(uris=[uri])` /
# `context.core.library.lookup(uris=[track_uri])` へ直接渡してしまう不具合。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが
# (サブエージェントに調査を委任した上で) 再調査して新規発見した項目。
#
# `add()` は `urllib.parse.urlparse(uri).scheme != ""` を事前チェックし、スキーム
# 無しなら `context.browse(uri, lookup=False)` 経由で解決してから常にスキーム付き
# URI へ変換した上で `tracklist.add()` を呼ぶ安全な設計になっている
# (current_playlist.py 290-298行目) が、`addid()`/`playlistadd()` にはこのガードが
# 無く、URI をそのまま `tracklist.add()`/`library.lookup()` へ渡している。
#
# `mopidy.core.TracklistController.add()`/`LibraryController.lookup()` は内部で
# `mopidy.internal.validation.check_uris()`/`check_uri()` を呼んでおり、各 URI に
# 対し `urllib.parse.urlparse(uri).scheme == ""` なら `mopidy.exceptions.
# ValidationError` (`ValueError` のサブクラス、mopidy_mpd 独自の
# `exceptions.MpdAckError` 系統ではない) を送出する。ソース確認済み。
# `mopidy_mpd/dispatcher.py` の `handle_request()` は `except exceptions.
# MpdAckError` と `except pykka.ActorDeadError` しか捕捉しないため、この
# `ValidationError` は pykka actor を未捕捉例外のまま突き抜け、当該コネクションが
# 応答無しで即切断される (mpdrawuriguard-patch.py が `readcomments`/`lsinfo` の
# 生URIフォールバックで修正したのと全く同型のバグの横展開漏れ)。
#
# 修正方針: mpdrawuriguard-patch.py と同じ変換方針で、`ValidationError` を捕捉し
# 「そんな曲は無い」と同義に扱う。`addid()`/`playlistadd()` はいずれも直後に
# 既存の空チェック (`if not tl_tracks`/`if not new_tracks`) で
# `exceptions.MpdNoExistError("No such song")` を送出する構造のため、
# 捕捉時に空のtracklist/lookup結果を返すだけで既存の空チェックにそのまま
# 委譲でき、追加のACK変換コードが不要 (mpdrawuriguard-patch.py の
# `_mpd_lookup_uri_or_no_such_song` と同じ「空に丸める」設計)。
# current_playlist.py/stored_playlists.py はそれぞれ独立モジュールで、
# mpdplaylistemptyname-patch.py と同じ理由(循環import回避)によりヘルパーは
# 共有せず各ファイルへ直接複製する。

import ast

p1 = "mopidy_mpd/protocol/current_playlist.py"
s1 = open(p1).read()

MARKER1 = "        tl_tracks = context.core.tracklist.add(\n            uris=[uri], at_position=at_position\n        ).get()\n    except mopidy.exceptions.ValidationError:"
if MARKER1 in s1:
    print("current_playlist.py addid() already patched for raw-uri guard, skip")
else:
    OLD1 = (
        "    tl_tracks = context.core.tracklist.add(\n"
        "        uris=[uri], at_position=at_position\n"
        "    ).get()\n"
        "\n"
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
    )
    assert s1.count(OLD1) == 1, f"OLD1 count={s1.count(OLD1)}"
    NEW1 = (
        "    import mopidy.exceptions\n"
        "\n"
        "    try:\n"
        "        tl_tracks = context.core.tracklist.add(\n"
        "            uris=[uri], at_position=at_position\n"
        "        ).get()\n"
        "    except mopidy.exceptions.ValidationError:\n"
        "        # uri がスキーム無し (実MPD流の素のパス等) で mopidy の URI として\n"
        "        # 不正な場合。add() と違い browse() 経由の解決は行わず、\n"
        "        # mpdrawuriguard-patch.py と同じ扱いで「そんな曲は無い」に丸める。\n"
        "        tl_tracks = []\n"
        "\n"
        "    if not tl_tracks:\n"
        '        raise exceptions.MpdNoExistError("No such song")\n'
    )
    s1 = s1.replace(OLD1, NEW1, 1)
    open(p1, "w").write(s1)
    ast.parse(s1)
    print(
        "patched current_playlist.py: addid()がスキーム無しURIでcore.tracklist."
        "add()のValidationErrorを未捕捉のままセッション切断してしまう不具合を修正"
    )

p2 = "mopidy_mpd/protocol/stored_playlists.py"
s2 = open(p2).read()

MARKER2 = "        try:\n            lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n        except mopidy.exceptions.ValidationError:"
if MARKER2 in s2:
    print("stored_playlists.py playlistadd() already patched for raw-uri guard, skip")
else:
    OLD2 = (
        "        lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n"
        "        new_tracks = [\n"
        "            track for uri_tracks in lookup_res.values() for track in uri_tracks\n"
        "        ]\n"
        "        if not new_tracks:\n"
        '            raise exceptions.MpdNoExistError("No such song")\n'
    )
    assert s2.count(OLD2) == 1, f"OLD2 count={s2.count(OLD2)}"
    NEW2 = (
        "        import mopidy.exceptions\n"
        "\n"
        "        try:\n"
        "            lookup_res = context.core.library.lookup(uris=[track_uri]).get()\n"
        "        except mopidy.exceptions.ValidationError:\n"
        "            # uri がスキーム無しで mopidy の URI として不正な場合。\n"
        "            # mpdrawuriguard-patch.py と同じ扱いで「そんな曲は無い」に丸める。\n"
        "            lookup_res = {}\n"
        "        new_tracks = [\n"
        "            track for uri_tracks in lookup_res.values() for track in uri_tracks\n"
        "        ]\n"
        "        if not new_tracks:\n"
        '            raise exceptions.MpdNoExistError("No such song")\n'
    )
    s2 = s2.replace(OLD2, NEW2, 1)
    open(p2, "w").write(s2)
    ast.parse(s2)
    print(
        "patched stored_playlists.py: playlistadd()がスキーム無しURIでcore."
        "library.lookup()のValidationErrorを未捕捉のままセッション切断してしまう"
        "不具合を修正"
    )
