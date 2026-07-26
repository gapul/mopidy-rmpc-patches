# mopidy-mpd 3.3.0 の translator.py `track_to_mpd_format()` (playlistinfo/find/search/
# count/listplaylistinfo/currentsong/playlistfind/playlistsearch 全てのトラック整形処理が
# 共有する唯一の関数) が Genre/Disc/Composer/Performer 等の全ての「値があれば出す」系
# タグを網羅する一方、`track.comment` だけは一切参照せずどのコマンドの応答にも
# `Comment:` 行を出力しない不具合。TODO 全項目消化済みのため自走エージェントが
# 調査して新規発見・追加した項目。
#
# 根拠: `Comment` は mopidy_mpd/protocol/tagtype_list.py の TAGTYPE_LIST に元々含まれる
# 非フィクションのタグで、session.py はクライアント接続時の既定 tagtypes に
# TAGTYPE_LIST 全体 (Comment 含む) を設定する。つまり rmpc 等は接続直後の `tagtypes`
# 応答で「Comment は有効」と伝えられるにもかかわらず、実際に `track.comment` へ値を
# 入れても track_to_mpd_format() がその値を読む経路自体を持たないため
# find/search/playlistinfo/currentsong のどの応答にも絶対に出てこない。
# 同じ music_db.py 内の `readcomments` ハンドラ (mpdreadcomments-patch.py で有効化済み)
# は `tracks[0].comment` を直接読んで正しく返せており、`track.comment` が
# バックエンドの持つ正当なフィールドであることは実装内で既に証明済み。
# Genre/Disc という他の「値があれば出す」系フィールドと全く同型の欠落であり、
# 意図的なスコープ外ではなく単純な網羅漏れ。
#
# 実害: rmpc (mierak/rmpc) はテーマ/ソート設定で任意の Tag::Custom("Comment") を
# 曲のプロパティ列やソートキーとして参照できるため、`tagtypes` が Comment を
# 有効と宣言しているのに実データが常に空欄に見えてしまう。
p = "mopidy_mpd/translator.py"
s = open(p).read()

MARKER = "if track.comment:"
if MARKER in s:
    print("translator.py already patched (comment tag), skip")
else:
    old_block = (
        '    if track.disc_no:\n'
        '        result.append(("Disc", track.disc_no))\n'
        "\n"
        "    if track.last_modified:\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
        '    if track.disc_no:\n'
        '        result.append(("Disc", track.disc_no))\n'
        "\n"
        "    if track.comment:\n"
        '        result.append(("Comment", track.comment))\n'
        "\n"
        "    if track.last_modified:\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)
    open(p, "w").write(s)
    print(
        "patched translator.py: track_to_mpd_format() が track.comment を "
        '"Comment" タグとして出力するよう修正 (Genre/Discと同じ流儀)'
    )
