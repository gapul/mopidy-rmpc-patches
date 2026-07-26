# mopidy-mpd 3.3.0 の translator.py `track_to_mpd_format()` (playlistinfo/playlistid/
# find/search/count/listplaylistinfo/currentsong/playlistfind/playlistsearch 全ての
# トラック整形処理が共有する唯一の関数) が `Track` タグを組み立てる際、
# `track.album.num_tracks` が既知 (アルバムの総トラック数が分かっている) だが
# `track.track_no` が未知 (mopidy core の Track.track_no のデフォルト値は None、
# 実際に `python3 -c "from mopidy.models import Track; print(Track().track_no)"` で
# 確認済み) の場合に `f"{track.track_no or 0}/{num_tracks}"` で "0/N" という
# 「トラック0番」を捏造してしまう不具合。TODO 全項目消化済みのため自走エージェントが
# 調査して新規発見・追加した項目。
#
# 根拠: 実 MPD (TRACKNUMBER タグの値をそのまま透過するのみ) はファイルに
# TRACKNUMBER タグが無ければ Track フィールド自体を出力しない。位置(N)が不明なまま
# 総数(M)だけを "0/M" として捏造することは実 MPD のいかなる実装経路にも存在しない
# (TRACKNUMBER が "N" や "N/M" 形式で存在する場合のみ Track を出す。総数だけを
# 知っていて位置を知らない、という組み合わせ自体が実ファイルのタグ付けでは発生しない)。
# さらに直後の `_has_value()` によるフィルタは `bool(value)` 判定のため、
# album が無い経路の `track.track_no or 0` (int 0) は falsy として除去される一方、
# album がある経路の f-string "0/N" (非空文字列) は常に truthy で除去されず、
# 「album の有無だけで track_no=0/None のときの出力有無が変わる」という
# 実装内で閉じた非一貫性にもなっている。
#
# 実害: mopidy_ytmusic の `uploadAlbumToTracks()` (library.py) は
# track_no を常に None にしたまま album (num_tracks 既知) を紐付けてトラックを
# 生成するため、YouTube Music の「アップロード」ライブラリのアルバムを
# ブラウズ/再生するだけで全曲が `Track: 0/N` として返る。rmpc本体
# (mierak/rmpc) を実際に clone してソース確認したところ、
# rmpc/src/ui/song_ext.rs `SongProperty::Track` (トラック番号列表示) と
# rmpc/src/ui/dir_or_song.rs (トラック番号によるソートキー) の双方が
# この値を素の整数として `parse::<u32>()`/`opt_str_parse` するため、
# "0/12" のような "/" を含む文字列は parse に失敗し、表示欄がフォールバックの
# 生文字列 "0/12" になったり、ソート時に数値として扱われず末尾または先頭に
# 固まってしまう実害がある。
#
# 修正方針: track_no が None (=未知) のときは総トラック数が分かっていても
# Track タグ自体を出力しない (Genre/Disc 等の他の「無ければ省略」系タグと
# 同じ流儀に揃える)。track_no が明示的に 0 (実ファイルの TRACKNUMBER="0" 相当)
# の場合の既存の挙動 (album有無に関わらず _has_value の bool(0)/bool("0/N") 判定に
# 委ねる) は変更しない。

pp = "mopidy_mpd/translator.py"
s = open(pp).read()

MARKER = "if track.track_no is not None:"
if MARKER in s:
    print("translator.py already patched, skip")
else:
    old_block = (
        "    if track.album is not None and track.album.num_tracks is not None:\n"
        "        result.append(\n"
        '            ("Track", f"{track.track_no or 0}/{track.album.num_tracks}")\n'
        "        )\n"
        "    else:\n"
        '        result.append(("Track", track.track_no or 0))\n'
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "    if track.track_no is not None:\n"
        "        if track.album is not None and track.album.num_tracks is not None:\n"
        "            result.append(\n"
        '                ("Track", f"{track.track_no}/{track.album.num_tracks}")\n'
        "            )\n"
        "        else:\n"
        '            result.append(("Track", track.track_no))\n'
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(pp, "w").write(s)
    print(
        "patched translator.py: track_no が未知(None)のとき Track タグの "
        '"0/N" 捏造を止め、他の欠落タグと同様にタグ自体を省略するよう修正'
    )
