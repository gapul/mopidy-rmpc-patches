# rmpcのDirectoriesペインで仮想パス(ディレクトリのlsinfo表示パス)を
# `find "(File starts_with '...')"`で検索するケースはmpdfindvirtualpath-patch.py
# がfind()のみ修正したが、同じ`_query_from_mpd_search_parameters`/
# `_mpd_pop_positives`パターンを個別に持つ兄弟コマンド findadd/searchadd/
# searchaddpl/count/searchcount は未修正のまま残っており、rmpcのDirectories
# ペインで「一括操作」ではなく「そのままキューに追加」「プレイリストへ追加」
# 「曲数/再生時間を数える」系の操作を行うと同じ0曲/0件バグが再現する。TODO
# 全項目消化済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を経て)新規発見。BACKLOG.mdを"findadd.*virtual"/"virtual.*findadd"/
# "searchadd.*virtual"/"_mpd_resolve_virtual_path_tracks"で検索し既出・
# mpdfindvirtualpath-patch.py自身がfind()以外に触れていないことを確認済み。
#
# 実機確認(dev mopidy, TCP 6601, mopidy-ytmusic実アカウント、
# "YouTube Music/Home/Quick picks"=7曲の実セクション):
#   find "(File starts_with '...')" → 7曲 (mpdfindvirtualpath-patch.py既存修正、正常)
#   clear; findadd "(File starts_with '...')"; status
#     → 修正前 playlistlength: 0 (silently添加されない)
#   clear; searchadd "(file starts_with '...')"; status
#     → 修正前 playlistlength: 0
#   searchaddpl "vpathtest" "(File starts_with '...')"; listplaylistinfo "vpathtest"
#     → 修正前 空
#   count "(File starts_with '...')" / searchcount ...
#     → 修正前 songs: 0 / playtime: 0
#   (対照: add "YouTube Music/Home/Quick picks" は既存の別経路で無関係、
#    修正前後とも7曲正常に追加される)
#
# 修正方針: mpdfindvirtualpath-patch.pyが導入した
# _mpd_resolve_virtual_path_tracks(context, negatives, positives)
# (sole positiveがuri/starts_with系、negatives無しの場合のみ
# dispatcher.pyのcontext.browse(path, recursive=True, lookup=True)で
# 仮想パスを実URIツリーへ解決、非該当時はNoneを返し無変更フォールバック)
# を、findadd/searchadd/searchaddpl/count・searchcount共有の
# _mpd_count_grouped()のungrouped分岐、の4箇所へ同じ形で配線する。
# 各箇所ともbackend検索(context.core.library.search)呼び出しの直前に
# 分岐を挿入するだけで、解決失敗時は既存コードパス(exact検索→
# ローカルpositives/negatives再フィルタ)へ無変更で流れるため退行リスクは無い。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "# mpdvpathaddcount-patch"
if MARKER in s:
    print("findadd/searchadd/searchaddpl/count/searchcountのディレクトリ仮想パス解決は既に適用済み、skip")
else:
    # --- count / searchcount が共有する _mpd_count_grouped() ---
    old_count_grouped = '''    if not groups:
        results = context.core.library.search(query=query, exact=exact).get()
        result_tracks = _mpd_filter_negatives(
            _get_tracks(results), negatives, case_sensitive=case_sensitive, strip_diacritics=strip_diacritics
        )
        result_tracks = _mpd_filter_positives(
            result_tracks, positives, case_sensitive=case_sensitive, strip_diacritics=strip_diacritics
        )
        total_length = sum(t.length for t in result_tracks if t.length)
        return [
            ("songs", len(result_tracks)),
            ("playtime", int(total_length / 1000)),
        ]'''
    assert s.count(old_count_grouped) == 1, f"old_count_grouped count={s.count(old_count_grouped)}"
    new_count_grouped = '''    if not groups:
        _mpdvpath_tracks = _mpd_resolve_virtual_path_tracks(context, negatives, positives)  # mpdvpathaddcount-patch
        if _mpdvpath_tracks is not None:
            result_tracks = _mpdvpath_tracks
        else:
            results = context.core.library.search(query=query, exact=exact).get()
            result_tracks = _mpd_filter_negatives(
                _get_tracks(results), negatives, case_sensitive=case_sensitive, strip_diacritics=strip_diacritics
            )
            result_tracks = _mpd_filter_positives(
                result_tracks, positives, case_sensitive=case_sensitive, strip_diacritics=strip_diacritics
            )
        total_length = sum(t.length for t in result_tracks if t.length)
        return [
            ("songs", len(result_tracks)),
            ("playtime", int(total_length / 1000)),
        ]'''
    s = s.replace(old_count_grouped, new_count_grouped, 1)

    # --- findadd() ---
    old_findadd = '''    results = context.core.library.search(
        query=query, exact=_mpd_backend_search_exact(True, _positives)
    ).get()
    tracks = _mpd_filter_negatives(
        _get_tracks(results), _negatives, case_sensitive=True
    )
    tracks = _mpd_filter_positives(tracks, _positives, case_sensitive=True)
    if _sort_field:
        tracks = _mpd_sort_tracks(tracks, _sort_field, _sort_desc)
    if _window is not None:
        tracks = tracks[_window]'''
    assert s.count(old_findadd) == 1, f"old_findadd count={s.count(old_findadd)}"
    new_findadd = '''    _mpdvpath_tracks = _mpd_resolve_virtual_path_tracks(context, _negatives, _positives)  # mpdvpathaddcount-patch
    if _mpdvpath_tracks is not None:
        tracks = _mpdvpath_tracks
    else:
        results = context.core.library.search(
            query=query, exact=_mpd_backend_search_exact(True, _positives)
        ).get()
        tracks = _mpd_filter_negatives(
            _get_tracks(results), _negatives, case_sensitive=True
        )
        tracks = _mpd_filter_positives(tracks, _positives, case_sensitive=True)
    if _sort_field:
        tracks = _mpd_sort_tracks(tracks, _sort_field, _sort_desc)
    if _window is not None:
        tracks = tracks[_window]'''
    s = s.replace(old_findadd, new_findadd, 1)

    # --- searchadd() ---
    old_searchadd = '''    results = context.core.library.search(query).get()
    tracks = _mpd_filter_negatives(
        _get_tracks(results), _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics
    )
    tracks = _mpd_filter_positives(
        tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics
    )
    if _sort_field:
        tracks = _mpd_sort_tracks(tracks, _sort_field, _sort_desc)
    if _window is not None:
        tracks = tracks[_window]'''
    assert s.count(old_searchadd) == 1, f"old_searchadd count={s.count(old_searchadd)}"
    new_searchadd = '''    _mpdvpath_tracks = _mpd_resolve_virtual_path_tracks(context, _negatives, _positives)  # mpdvpathaddcount-patch
    if _mpdvpath_tracks is not None:
        tracks = _mpdvpath_tracks
    else:
        results = context.core.library.search(query).get()
        tracks = _mpd_filter_negatives(
            _get_tracks(results), _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics
        )
        tracks = _mpd_filter_positives(
            tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics
        )
    if _sort_field:
        tracks = _mpd_sort_tracks(tracks, _sort_field, _sort_desc)
    if _window is not None:
        tracks = tracks[_window]'''
    s = s.replace(old_searchadd, new_searchadd, 1)

    # --- searchaddpl() (with _stored_playlist_edit_lock ブロック内、8スペースインデント) ---
    old_searchaddpl = '''        results = context.core.library.search(query).get()
        _new_tracks = _mpd_filter_negatives(
            _get_tracks(results), _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics
        )
        _new_tracks = _mpd_filter_positives(
            _new_tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics
        )
        if _sort_field:
            _new_tracks = _mpd_sort_tracks(_new_tracks, _sort_field, _sort_desc)
        if _window is not None:
            _new_tracks = _new_tracks[_window]'''
    assert s.count(old_searchaddpl) == 1, f"old_searchaddpl count={s.count(old_searchaddpl)}"
    new_searchaddpl = '''        _mpdvpath_tracks = _mpd_resolve_virtual_path_tracks(context, _negatives, _positives)  # mpdvpathaddcount-patch
        if _mpdvpath_tracks is not None:
            _new_tracks = _mpdvpath_tracks
        else:
            results = context.core.library.search(query).get()
            _new_tracks = _mpd_filter_negatives(
                _get_tracks(results), _negatives, case_sensitive=False, strip_diacritics=_strip_diacritics
            )
            _new_tracks = _mpd_filter_positives(
                _new_tracks, _positives, case_sensitive=False, strip_diacritics=_strip_diacritics
            )
        if _sort_field:
            _new_tracks = _mpd_sort_tracks(_new_tracks, _sort_field, _sort_desc)
        if _window is not None:
            _new_tracks = _new_tracks[_window]'''
    s = s.replace(old_searchaddpl, new_searchaddpl, 1)

    open(p, "w").write(s)
    print(
        "patched music_db.py: findadd/searchadd/searchaddpl/count/searchcountに"
        "ディレクトリ仮想パス→実URIツリー解決を配線(rmpc Directoriesペインでの"
        "追加/プレイリスト保存/カウント操作が0曲扱いになる不具合を修正)"
    )
