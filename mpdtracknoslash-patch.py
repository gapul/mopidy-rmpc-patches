# mopidy-mpd 3.3.0 の translator.py `track_to_mpd_format()` (playlistinfo/playlistid/
# find/search/count/listplaylistinfo/currentsong/playlistfind/playlistsearch 全ての
# トラック整形処理が共有する唯一の関数) は、mpdtracknofabricate-patch.py 適用後も
# track.track_no と track.album.num_tracks が両方既知の (mopidy_ytmusic で最も
# 頻繁に踏む) 通常ケースでは依然として `Track: {track_no}/{num_tracks}` という
# スラッシュ結合形式を出力する。TODO 全項目消化済みのため自走エージェントが
# (general-purpose サブエージェントへの調査委任を経て) 新規発見。
#
# 根拠: mpdtracknofabricate-patch.py 自身のコメントが既に「rmpc本体
# (mierak/rmpc) の rmpc/src/ui/song_ext.rs `SongProperty::Track` (トラック番号列
# 表示) と rmpc/src/ui/dir_or_song.rs (トラック番号ソートキー) の双方がこの値を
# 素の整数として parse::<u32>()/opt_str_parse する」と記載していたが、当時は
# track_no が未知(None)なのに num_tracks だけ既知の捏造ケースのみを修正対象とし、
# track_no・num_tracks が両方既知の通常ケースの "N/M" 形式自体は温存していた。
# 実際に mierak/rmpc 本体を clone しソースを直接確認:
# rmpc/src/config/defaults.rs `default_song_sort()` はユーザーが何もカスタマイズ
# しなくても効く既定ソート順を [Disc, Track, Artist, Title] と定義しており、
# rmpc/src/ui/dir_or_song.rs の SongProperty::Track 比較は
# `CmpByProp::opt_str_parse::<_, i32>(...)` で両辺を `.parse::<i32>()` し、
# 両方失敗した場合 (`(Err(_), Err(_))`) にのみ文字列比較にフォールバックする。
# "3/12" と "10/12" はどちらも i32 parse に失敗するため両方とも文字列比較に落ち、
# "10/12" < "3/12" (先頭文字 '1' < '3') という辞書順でソートされてしまう —
# アルバムを開いた既定のトラック順が破綻する (10曲目以降が2桁目以降の曲より
# 前に来る)。rmpc/src/ui/song_ext.rs のトラック番号列表示も同様に
# `v.last().parse::<u32>()` に失敗すると生の "N/M" 文字列がそのままフォール
# バック表示され、パースに成功する曲 (ゼロ埋め "01"/"02" 表示) と混在して
# 列が不揃いになる。
#
# 実 MPD は TRACKNUMBER タグの値をファイルから読んだ文字列としてそのまま
# 透過するだけで、位置(N)と総数(M)という別々の整数フィールドをサーバー実装が
# 自ら合成してスラッシュ結合する経路は存在しない。mopidy_ytmusic の Track は
# track_no/album.num_tracks を最初から分離した整数として保持しており「ファイルに
# 元から "N/M" という生タグ文字列が入っていた」という実データも存在しないため、
# num_tracks 側は MPD の Track フィールドには本来出力すべきでない付加情報を
# 実装側で無理に結合していたにすぎない。修正方針: track.album.num_tracks の
# 有無に関わらず、track_no が既知なら常にその整数単体を Track タグとして出力する
# (num_tracks との結合を廃止)。

pp = "mopidy_mpd/translator.py"
s = open(pp).read()

MARKER = "if track.track_no is not None:\n        result.append"
if MARKER in s:
    print("translator.py already patched (mpdtracknoslash), skip")
else:
    old_block = (
        "    if track.track_no is not None:\n"
        "        if track.album is not None and track.album.num_tracks is not None:\n"
        "            result.append(\n"
        '                ("Track", f"{track.track_no}/{track.album.num_tracks}")\n'
        "            )\n"
        "        else:\n"
        '            result.append(("Track", track.track_no))\n'
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        "    if track.track_no is not None:\n"
        '        result.append(("Track", track.track_no))\n'
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(pp, "w").write(s)
    print(
        "patched translator.py: Track タグへの album.num_tracks スラッシュ結合"
        "(N/M形式)を廃止し、track_no既知時は常に整数単体を出力するよう修正"
        " (rmpcのdefault_song_sort Track比較/表示のparse失敗を解消)"
    )
