# `playlistlength {NAME}` (mpdplaylistlength-patch.py で実装済み) の `playtime`
# フィールドが `int(total_length / 1000)` で常に切り捨てになっている不具合を修正。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが (general-purpose
# サブエージェントへの調査委任を経て) 新規発見。
#
# mpdplaylistlength-patch.py 自身の検証ログ (BACKLOG.md) は「実MPDと同じ切り捨て、
# count/statsと同じ丸め規約」と結論づけていたが、これは実際には
# `src/playlist/Length.cxx` を確認せずに書かれた誤った結論だった。gh raw で
# 実際に `src/playlist/Length.cxx` (`playlist_provider_length()`) を取得して
# 確認すると、`playtime += get_duration(*song)` でミリ秒精度に積算した後
# `std::chrono::round<std::chrono::seconds>(playtime)` で最近接秒への丸め
# (四捨五入、tie-breakはround-half-to-even) を行っている。一方 `count`/
# `searchcount`/`stats` が使う `src/db/Count.cxx` は
# `std::chrono::duration_cast<std::chrono::seconds>(...)` で切り捨てており、
# 実MPD内部でも playlistlength と count系とで丸め規約は非対称 (兄弟コマンドの
# 丸め規約が一致するという過去の思い込みが誤りだった一例)。
# BACKLOG.md を "playtime"/"round"/"duration_cast" 等で検索したが本件は既出無し。
#
# 修正: `int(total_length / 1000)` (切り捨て) を `round(total_length / 1000)`
# (最近接丸め、Python組み込みroundもtie-breakがround-half-to-evenでreal MPDの
# std::chrono::roundと同じ規約) に変更するのみ。count/stats側 (mpdcount-patch.py/
# mpdstats-patch.py) は実MPDのCount.cxx同様の切り捨てのままで正しいため無変更。

p = "mopidy_mpd/protocol/stored_playlists.py"
s = open(p).read()

OLD = '        ("playtime", int(total_length / 1000)),\n'
NEW = '        ("playtime", round(total_length / 1000)),\n'

if OLD not in s:
    print("playlistlength playtime already rounded (or anchor missing), skip")
else:
    assert s.count(OLD) == 1, f"anchor count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched stored_playlists.py: playlistlength の playtime を "
        "int()切り捨てからround()最近接丸めへ修正 (実MPD src/playlist/Length.cxx "
        "std::chrono::round準拠)"
    )
