# 曲メタデータ (currentsong/playlistinfo/find/search/listallinfo 等) に `Format`
# (samplerate:bits:channels、実MPDでは「その曲ファイルの音声フォーマット」を表す
# タグ) が一度も出力されない件。musicpd.org protocol docs (Song Metadata Format節)
# によれば Format は `status` の `audio` (再生中デコーダの実際の出力) とは別物で、
# find/search/playlistinfo/currentsong/listallinfo/lsinfo の各曲行に載る。
#
# rmpc 本体 (mierak/rmpc) を実際に clone して調査したところ、rmpc-mpd/src/commands/
# current_song.rs の `Song::samplerate()`/`bits()`/`channels()` が
# `self.metadata.get("format")` (曲の "Format" タグ) を ":" 分割してパースする実装で、
# rmpc/src/ui/song_ext.rs の `SongProperty::SampleRate()`/`Bits()`/`Channels()`
# (テーマの song_format で曲一覧やヘッダーに配置できるプロパティ、
# rmpc/src/config/theme/properties.rs で定義・SongPropertyFile経由でTOMLから設定可) が
# 実際にこの値を描画に使う実装と確認した。mpdaudioformat-patch.py が追加した
# status の audio (Status::samplerate() 等、ステータスバー用) とは別の、曲そのものの
# プロパティとして曲一覧に列表示できる機能であり、Format が常に欠落している限り
# ユーザーがテーマでこれらの SongProperty を配置しても永久に空欄のままになる
# 実害あるギャップ。
#
# 実装: mopidy core / mopidy-ytmusic はファイルの音声フォーマットを事前に(スキャン等
# で)把握する仕組みを持たないため(decoders/audio と同種の限界)、
# mpdaudioformat-patch.py が追加した `_audio_format` 揮発性ストアを拡張し、
# どの曲(uri)のものかも一緒に記録する。ytsongformat-patch.py (mopidy_ytmusic) が
# ytaudioformat-patch.py の書き込み箇所に uri を追加で渡すよう対応する。
# track_to_mpd_format はその曲の uri が直近解決した uri と一致する時だけ Format を
# 出力する (実際に判明している曲についてのみ出す、実MPDの「わからなければ省略」と
# 同じ振る舞い)。
#
# 既知の制約: mpdaudioformat-patch.py と同じく bits は固定値 "16"
# (yt-dlp のformat情報からは得られないためGStreamerの一般的なPCMデコード出力を仮定)。
# また「直近に解決した1曲」のみを記憶する揮発性ストアのため、複数曲の Format を
# 同時に把握しているわけではない(実MPDはDBスキャン済み全曲のFormatを常時把握するが、
# 本パッチはストリーミングバックエンドの性質上、再生時に解決された曲のみ分かる)。

tp = "mopidy_mpd/translator.py"
t = open(tp).read()

MARKER = "_audio_format_uri"
if MARKER in t:
    print("translator.py already patched (song format store), skip")
else:
    old_store = (
        "_audio_format = None\n"
        "\n"
        "\n"
        "def set_audio_format(value):\n"
        "    global _audio_format\n"
        "    _audio_format = value\n"
        "\n"
        "\n"
        "def get_audio_format():\n"
        "    return _audio_format\n"
    )
    assert t.count(old_store) == 1, f"old_store count={t.count(old_store)}"
    new_store = (
        "_audio_format = None\n"
        "_audio_format_uri = None\n"
        "\n"
        "\n"
        "def set_audio_format(value, uri=None):\n"
        "    global _audio_format, _audio_format_uri\n"
        "    _audio_format = value\n"
        "    _audio_format_uri = uri\n"
        "\n"
        "\n"
        "def get_audio_format():\n"
        "    return _audio_format\n"
        "\n"
        "\n"
        "def get_song_audio_format(uri):\n"
        "    # 曲メタデータの Format タグ用。直近に解決した曲(uri)と一致する時だけ返す。\n"
        "    if uri and _audio_format and uri == _audio_format_uri:\n"
        "        return _audio_format\n"
        "    return None\n"
    )
    t = t.replace(old_store, new_store, 1)

    anchor = (
        '        *multi_tag_list(track.artists, "name", "Artist"),\n'
        '        ("Album", track.album and track.album.name or ""),\n'
        "    ]\n"
        "\n"
        "    if stream_title is not None:"
    )
    assert t.count(anchor) == 1, f"anchor count={t.count(anchor)}"
    replacement = (
        '        *multi_tag_list(track.artists, "name", "Artist"),\n'
        '        ("Album", track.album and track.album.name or ""),\n'
        "    ]\n"
        "\n"
        "    song_format = get_song_audio_format(track.uri)\n"
        "    if song_format:\n"
        '        result.append(("Format", song_format))\n'
        "\n"
        "    if stream_title is not None:"
    )
    t = t.replace(anchor, replacement, 1)

    open(tp, "w").write(t)
    print("patched translator.py: 曲メタデータに Format (samplerate:bits:channels) を追加")
