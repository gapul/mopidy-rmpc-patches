# mpdadded-patch.py が実装した MPD 0.24+ の "Added" (ISO 8601、曲がいつ追加されたか) は
# translator.py の track_to_mpd_format() 内、`position is not None and tlid is not None`
# (=キュー内の曲) の分岐でのみ出力される。だが rmpc 本体 (mierak/rmpc) を実際に clone して
# ソース確認したところ、rmpc-mpd/src/commands/current_song.rs の `Song.added` フィールドは
# キュー由来かどうかを問わず全ての曲情報応答で解釈される汎用フィールドで、
# rmpc/src/config/theme/properties.rs の `SongProperty::Added()` として
# rmpc/src/ui/dir_or_song.rs (`CmpByProp::cmp(a.added, b.added)`、検索結果/タグブラウザ/
# ディレクトリ/ストアドプレイリストいずれのペインでも使える汎用ソート・カラム表示プロパティ)
# から参照される。実機 (`find`/`search`/`lsinfo`/`listplaylistinfo`) で確認したところ、
# これらキュー外の経路は position/tlid を渡さないため "Added" 行そのものが常に欠落しており、
# ユーザーが検索結果やプレイリストのペインで Added 列表示・Added ソートを設定しても常に
# 空欄になる実害がある。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (Explore サブエージェントへの調査委任を経て) mopidy_mpd/rmpc を横断的に再調査して
# 新規発見した項目。
#
# mopidy core の Track モデルには「ライブラリに実際に追加された時刻」という概念が無く
# (mopidy-ytmusic はYouTube Music側のカタログをその都度動的に返すだけで、mpdadded-patch.py
# の docstring 通りDBという概念自体が無い)、真の意味論を再現するのは不可能なため、
# mpdadded-patch.py のキュー用揮発性ストアと同じ設計方針(プロセスの生涯の中で
# 「このMPDセッションで最初にその曲が返された時刻」を疑似的なAddedとして採用)を、
# キュー外の経路(uriキー)にも適用する。同一uriがキューにも同時に載っている場合、
# キュー側は独立した _queue_added (tlidキー、キューへの追加のたびに新しい値になる)
# を引き続き使うため、本パッチは既存のキュー内Addedの見え方を一切変えない。
#
# ytlibrarycachecap-patch.py (mopidy_ytmusic側の無制限dictキャッシュ問題) と同根の
# 再発を避けるため、こちらも上限付きFIFOキャッシュ (mpdaudioformatpreload-patch.py の
# _audio_format_cache と同じ流儀) とする。
tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER = "_library_added"
if MARKER in t:
    print("translator.py already patched (library Added), skip")
else:
    anchor_store = (
        "def get_added(tlid):\n"
        "    with _queue_lock:\n"
        "        return _queue_added.get(tlid)\n"
    )
    assert t.count(anchor_store) == 1, f"anchor_store count={t.count(anchor_store)}"
    new_store = anchor_store + (
        "\n"
        "\n"
        "# キュー外(find/search/lsinfo/listplaylistinfo等)で返す曲用の疑似 Added。\n"
        "# uri -> ISO8601文字列。このMPDセッションで最初にその曲(uri)を返した時刻を\n"
        "# 記録するだけの近似値(真のライブラリ追加時刻は mopidy core に概念が無い)。\n"
        "# 無制限に増え続けないよう古い順(挿入順)に破棄する。\n"
        "_library_added = {}\n"
        "_LIBRARY_ADDED_CACHE_MAX = 8192\n"
        "\n"
        "\n"
        "def get_or_stamp_library_added(uri):\n"
        "    if not uri:\n"
        "        return None\n"
        "    with _queue_lock:\n"
        "        added = _library_added.get(uri)\n"
        "        if added is None:\n"
        "            added = datetime.datetime.now(datetime.timezone.utc).strftime(\n"
        '                "%Y-%m-%dT%H:%M:%SZ"\n'
        "            )\n"
        "            _library_added[uri] = added\n"
        "            while len(_library_added) > _LIBRARY_ADDED_CACHE_MAX:\n"
        "                _library_added.pop(next(iter(_library_added)))\n"
        "        return added\n"
    )
    t = t.replace(anchor_store, new_store, 1)

    anchor_format = (
        "        for extra_tag_type, extra_values in get_song_tags(tlid).items():\n"
        "            for extra_value in extra_values:\n"
        "                result.append((extra_tag_type, extra_value))\n"
    )
    assert t.count(anchor_format) == 1, f"anchor_format count={t.count(anchor_format)}"
    new_format = anchor_format + (
        "    else:\n"
        "        added = get_or_stamp_library_added(track.uri)\n"
        "        if added:\n"
        "            result.append((\"Added\", added))\n"
    )
    t = t.replace(anchor_format, new_format, 1)

    open(tp, "w").write(t)
    print(
        "patched translator.py: find/search/lsinfo/listplaylistinfo 等キュー外の曲情報にも "
        "疑似Added(このセッションで最初に返した時刻、uriキーの上限付きFIFOキャッシュ)を追加"
    )
