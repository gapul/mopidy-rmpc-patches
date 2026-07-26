# mopidy-mpd 3.3.0 の `playlistfind`/`playlistsearch` (mopidy_mpd/protocol/current_playlist.py)
# は musicpd.org 仕様 (現行: `playlistfind {FILTER} [sort {TYPE}] [window {START:END}]`) の
# うち、`playlistfind` は `tag=="filename"` の1ケースだけ実装したスタブ、`playlistsearch` は
# 完全な `raise MpdNotImplemented` のスタブのままだった。rmpc 自体はこれらを送らないが、
# 実 MPD 互換のギャップとして残っていたため、mpdsearch/mpdsort/mpdwindow-patch が
# music_db.py に用意したフィルタ式パーサ/sort/window ロジックをそのまま current_playlist.py
# から import して再利用し、キュー(current tracklist)内を検索できるようにする。
# 実 MPD 仕様 (WebFetch で mpd.readthedocs.io/protocol.html を確認済み):
#   - playlistfind: 大文字小文字を区別する厳密一致 (`find` 相当)
#   - playlistsearch: 大文字小文字を区別しない部分一致 (`search` 相当)
#   - どちらも複数マッチしうる (旧来の1件だけ返す実装は誤り)
#   - 新フィルタ式 `(Tag == "x")` / 旧来のタグ・値ペア、`sort`/`window` 修飾も同様に効く
#
# 追記 (mpdstringnorm-patch.py と対): 実 MPD の QueueCommands.cxx handle_playlistsearch は
# `client.StringNormalizationEnabled(SN_STRIP_DIACRITICS)` を読んで比較前に diacritics を
# 除去する (playlistfind は常に false のまま、strict一致に diacritics 除去は効かない仕様)。
# mpdstringnorm-patch.py が `context.session.string_normalization` にこの状態を保持するため、
# playlistsearch (strict=False) の場合のみ NFD分解→結合文字(Mark)除去→NFC再合成
# (実MPDのICU "NFD; [:M:] Remove; NFC" transliterator と同じアルゴリズム) を needle/value
# 双方に適用してから比較する。
p = "mopidy_mpd/protocol/current_playlist.py"
s = open(p).read()

MARKER = "_pf_field_values"
if MARKER in s:
    print("playlistfind/playlistsearch filter support already present, skip")
else:
    anchor_import = "from mopidy_mpd import exceptions, protocol, translator\n"
    assert s.count(anchor_import) == 1, f"anchor_import count={s.count(anchor_import)}"
    new_import = "import unicodedata\n\n" + anchor_import + (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _SEARCH_MAPPING,\n"
        "    _mpd_extract_sort_params,\n"
        "    _mpd_sort_value,\n"
        "    _query_from_mpd_search_parameters,\n"
        ")\n"
    )
    s = s.replace(anchor_import, new_import, 1)

    helper = '''

_PF_FIELDS = sorted(set(_SEARCH_MAPPING.values()) - {"any"})


def _pf_field_values(track, field):
    """指定フィールド(mopidyの内部フィールド名)の値を文字列リストで返す (無ければ空)。"""
    if field == "any":
        values = []
        for f in _PF_FIELDS:
            values.extend(_pf_field_values(track, f))
        return values
    if field == "uri":
        return [track.uri] if track.uri else []
    if field == "track_name":
        return [track.name] if track.name else []
    if field == "album":
        return [track.album.name] if track.album and track.album.name else []
    if field == "albumartist":
        artists = track.album.artists if track.album else []
        return [a.name for a in artists if a.name]
    if field == "artist":
        return [a.name for a in track.artists if a.name]
    if field == "composer":
        return [a.name for a in track.composers if a.name]
    if field == "performer":
        return [a.name for a in track.performers if a.name]
    if field == "genre":
        return [track.genre] if track.genre else []
    if field == "date":
        return [track.date] if track.date else []
    if field == "comment":
        return [track.comment] if track.comment else []
    if field == "disc_no":
        return [str(track.disc_no)] if track.disc_no is not None else []
    if field == "track_no":
        return [str(track.track_no)] if track.track_no is not None else []
    if field == "musicbrainz_trackid":
        return [track.musicbrainz_id] if track.musicbrainz_id else []
    if field == "musicbrainz_albumid":
        if track.album and track.album.musicbrainz_id:
            return [track.album.musicbrainz_id]
        return []
    if field == "musicbrainz_artistid":
        return [a.musicbrainz_id for a in track.artists if a.musicbrainz_id]
    return []


def _pf_strip_diacritics(text):
    """実MPDのICU "NFD; [:M:] Remove; NFC" transliteratorと同じアルゴリズム。"""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", stripped)


def _pf_matches(track, query, strict, strip_diacritics=False):
    for field, needles in query.items():
        values = _pf_field_values(track, field)
        if strip_diacritics:
            values = [_pf_strip_diacritics(v) for v in values]
        matched = False
        for needle in needles:
            cmp_needle = _pf_strip_diacritics(needle) if strip_diacritics else needle
            if strict:
                if cmp_needle in values:
                    matched = True
                    break
            elif any(cmp_needle.lower() in v.lower() for v in values):
                matched = True
                break
        if not matched:
            return False
    return True


def _pf_search(context, args, strict):
    if not args:
        raise exceptions.MpdArgError("wrong number of arguments")
    args, sort_field, descending, window = _mpd_extract_sort_params(args)
    if not args:
        raise exceptions.MpdArgError("wrong number of arguments")
    try:
        query = _query_from_mpd_search_parameters(args, _SEARCH_MAPPING)
    except ValueError:
        raise exceptions.MpdArgError("incorrect arguments")
    if not query:
        raise exceptions.MpdArgError("incorrect arguments")

    strip_diacritics = not strict and "strip_diacritics" in getattr(
        context.session, "string_normalization", ()
    )
    tl_tracks = context.core.tracklist.get_tl_tracks().get()
    matches = [
        (position, tl_track)
        for position, tl_track in enumerate(tl_tracks)
        if _pf_matches(tl_track.track, query, strict, strip_diacritics)
    ]
    if sort_field:
        matches.sort(
            key=lambda pt: _mpd_sort_value(pt[1].track, sort_field),
            reverse=descending,
        )
    if window is not None:
        matches = matches[window]

    result = []
    for position, tl_track in matches:
        formatted = translator.track_to_mpd_format(
            tl_track, context.session.tagtypes, position=position
        )
        if formatted:
            result.append(formatted)
    return result
'''
    anchor_helper = 'from mopidy_mpd.protocol.music_db import (\n'
    assert s.count(anchor_helper) == 1, f"anchor_helper count={s.count(anchor_helper)}"
    # helper を import ブロックの直後(既存関数群の手前)に挿入する
    import_block_end = (
        "from mopidy_mpd.protocol.music_db import (\n"
        "    _SEARCH_MAPPING,\n"
        "    _mpd_extract_sort_params,\n"
        "    _mpd_sort_value,\n"
        "    _query_from_mpd_search_parameters,\n"
        ")\n"
    )
    assert s.count(import_block_end) == 1, f"import_block_end count={s.count(import_block_end)}"
    s = s.replace(import_block_end, import_block_end + helper, 1)

    old_playlistfind = (
        '@protocol.commands.add("playlistfind")\n'
        "def playlistfind(context, tag, needle):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``playlistfind {TAG} {NEEDLE}``\n"
        "\n"
        "        Finds songs in the current playlist with strict matching.\n"
        '    """\n'
        '    if tag == "filename":\n'
        '        tl_tracks = context.core.tracklist.filter({"uri": [needle]}).get()\n'
        "        if not tl_tracks:\n"
        "            return None\n"
        "        position = context.core.tracklist.index(tl_tracks[0]).get()\n"
        "        return translator.track_to_mpd_format(\n"
        "            tl_tracks[0], context.session.tagtypes, position=position\n"
        "        )\n"
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert s.count(old_playlistfind) == 1, f"old_playlistfind count={s.count(old_playlistfind)}"

    new_playlistfind = (
        '@protocol.commands.add("playlistfind")\n'
        "def playlistfind(context, *args):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``playlistfind {FILTER} [sort {TYPE}] [window {START:END}]``\n"
        "\n"
        "        Finds songs in the current playlist with strict matching.\n"
        '    """\n'
        "    return _pf_search(context, args, strict=True)\n"
    )
    s = s.replace(old_playlistfind, new_playlistfind, 1)

    old_playlistsearch = (
        '@protocol.commands.add("playlistsearch")\n'
        "def playlistsearch(context, tag, needle):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``playlistsearch {TAG} {NEEDLE}``\n"
        "\n"
        "        Searches case-sensitively for partial matches in the current\n"
        "        playlist.\n"
        "\n"
        "    *GMPC:*\n"
        "\n"
        '    - uses ``filename`` and ``any`` as tags\n'
        '    """\n'
        "    raise exceptions.MpdNotImplemented  # TODO\n"
    )
    assert s.count(old_playlistsearch) == 1, f"old_playlistsearch count={s.count(old_playlistsearch)}"

    new_playlistsearch = (
        '@protocol.commands.add("playlistsearch")\n'
        "def playlistsearch(context, *args):\n"
        '    """\n'
        "    *musicpd.org, current playlist section:*\n"
        "\n"
        "        ``playlistsearch {FILTER} [sort {TYPE}] [window {START:END}]``\n"
        "\n"
        "        Searches case-insensitively for partial matches in the current\n"
        "        playlist.\n"
        "\n"
        "    *GMPC:*\n"
        "\n"
        '    - uses ``filename`` and ``any`` as tags\n'
        '    """\n'
        "    return _pf_search(context, args, strict=False)\n"
    )
    s = s.replace(old_playlistsearch, new_playlistsearch, 1)

    open(p, "w").write(s)
    print(
        "patched current_playlist.py: playlistfind/playlistsearch を "
        "FILTER式/sort/window対応・複数マッチ対応に拡張"
    )
