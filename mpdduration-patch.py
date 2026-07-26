# mopidy-mpd 3.3.0 の translator.py `track_to_mpd_format()` (playlistinfo/playlistid/
# find/search/count/listplaylistinfo/currentsong/playlistfind/playlistsearch 全ての
# トラック整形処理が共有する唯一の関数) は曲の長さを `Time` (整数秒、非推奨の legacy
# フィールド) としてのみ出力しており、MPD 0.20 で追加された後継フィールド `duration`
# (小数秒) を一度も出力していない。TODO 全項目消化済みのため自走エージェントが rmpc
# 本体 (mierak/rmpc) を実際に clone してソース確認したところ、rmpc-mpd/src/from_mpd.rs
# の `next()` はキーを必ず `to_lowercase()` してから `next_internal()` に渡すため、
# `Time: N` は小文字化された `"time"` として `current_song.rs` の
# `FromMpd for Song::next_internal` に届くが、そこでは `"time" => {} // deprecated or
# ignored` と明記されて完全に無視され、`self.duration` を実際にセットするのは
# `"duration" => { self.duration = Some(...) }` の1系統のみと判明。つまり mopidy_mpd が
# 送る全ての曲情報は rmpc からは常に `Song.duration == None` に見える。
#
# 実害を実際に確認: rmpc/src/ui/song_ext.rs `SongProperty::Duration`
# (キューテーブル/検索結果テーブルの "Duration" カラム描画元)・rmpc/src/ctx.rs
# `cached_queue_time_total` (キュー全体の合計時間)・rmpc/src/ui/panes/mod.rs
# (Now Playing欄の合計時間集計)・rmpc/src/ui/modals/info_list_modal.rs
# `total_duration` (アーティスト/アルバム詳細モーダルの合計時間) が軒並み
# `s.duration` (=常にNone) に依存しており、これらが全て空欄/0表示になる。
# さらに rmpc/src/shared/lrc/index.rs (歌詞 .lrc 同期機能) の `target_duration`
# フォールバックにも `song.duration` が使われており、歌詞位置合わせの精度にも影響する。
# 実 MPD 側の実装 (MusicPlayerDaemon/MPD src/SongPrint.cxx song_print_info、
# gh clone で実際にソース確認) は `Time`/`duration` を常にセットで1曲につき2行
# (`"Time: {}\nduration: {:1.3f}\n"`) 出力しており、mopidy_mpd 側がこの後継フィールドを
# 一度も送っていないこと自体が標準 MPD プロトコル準拠の欠落と判明した上で着手。
#
# 実装方針: 小数秒だが mopidy Track.length はミリ秒の整数のため情報源の精度はそのまま
# (実 MPD が音声デコーダのサブミリ秒精度を持つのと違い mopidy はミリ秒止まりだが、
# 桁数のフォーマットのみ実 MPD の `{:1.3f}` (小数点以下3桁) に合わせれば互換性は十分)。
# 既存の `Time` フィールドの `track.length and ... or 0` という「無ければ0」という
# best-effort な既存の流儀 (docstringでの言及なし、テストでも0が期待値) を崩さないよう、
# `duration` も同じ条件分岐で「無ければ0.000」にして Time と常に対になるようにする
# (実 MPD は length が無ければ Time/duration 行自体を丸ごと省略するが、mopidy_mpd の
# 既存 Time は無条件出力のため、ここだけ省略すると Time はあるのに duration は無いという
# 中途半端な非対称が生まれてしまうため、既存の Time の流儀に揃えるのが安全)。

pp = "mopidy_mpd/translator.py"
s = open(pp).read()

MARKER = '("duration", '
if MARKER in s:
    print("translator.py already patched, skip")
else:
    old_block = '        ("Time", track.length and (track.length // 1000) or 0),\n'
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '        ("Time", track.length and (track.length // 1000) or 0),\n'
        '        ("duration", round((track.length or 0) / 1000, 3)),\n'
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(pp, "w").write(s)
    print("patched translator.py: track_to_mpd_format に duration (MPD0.20+, Timeの後継) を追加")
