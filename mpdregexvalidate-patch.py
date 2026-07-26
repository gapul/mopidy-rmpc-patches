# mpdfilterkind-patch.py/mpdnegfilter-patch.py が実装した正規表現フィルタ
# (`(TAG =~ "VALUE")`/`(TAG !~ "VALUE")`) について、無効な正規表現 (閉じ括弧が
# 無い等コンパイルできないパターン) を渡した場合の実害。TODO 全項目消化済みの
# ため自走エージェントが横断調査 (mpdfilterkind-patch.py/mpdnegfilter-patch.py
# が追加した正規表現マッチ箇所を実データで実際に叩いて検証) して新規発見・
# 追加した項目。
#
# 実 MPD 仕様 (MusicPlayerDaemon/MPD を実際に clone してソース確認):
# src/song/Filter.cxx のフィルタ式パーサが `(TAG =~ "VALUE")` を読んだ時点で
# `f.SetRegex(std::make_shared<UniqueRegex>(f.GetValue().c_str(), ...))` を
# 即座に呼び出しており、src/lib/pcre/UniqueRegex.hxx の `Compile()` は
# 「Throws Pcre::Error on error.」と明記の通りコンパイル失敗時に例外を送出、
# これはコマンド全体を中断させ `ACK` (invalid argument 系) をクライアントへ
# 返す。つまり実 MPD は不正な正規表現をコマンドの引数解析の時点で拒否し、
# データベース照会は一切行わない。
#
# 現状の mopidy_mpd (mpdnegfilter-patch.py/mpdfilterkind-patch.py 適用後) は
# `_query_from_mpd_filter_expression()` (music_db.py, `find`/`findadd`/
# `search`/`searchadd`/`searchaddpl`/`count`/`searchcount` および
# current_playlist.py の `_pf_search()` 経由で `playlistfind`/`playlistsearch`/
# `searchplaylist` も共有) がこの時点では演算子とタグ名だけを見て
# `(field, "regex", value)` を positives/negatives へそのまま積むだけで、
# 実際に `re.compile(value)` を試すのはずっと後段の `_mpd_track_matches_positives()`/
# `_mpd_track_excluded()`/`_pf_matches()` (取得済み Track に対するローカル
# 後段フィルタ) であり、しかもそこでは `except re.error: continue` で
# 静かに握り潰し、そのフィルタ条件自体が「常に真」であるかのように扱われる。
#
# 実害: dev mopidy (6601, ytmusic 実アカウント) に実際に
# `find "(Artist =~ '(')"` (閉じ括弧の無い不正な正規表現) を送ったところ、
# 実 MPD なら即座に ACK になるはずが OK で応答し、しかも
# `query.setdefault(field, []).append(value)` で生の "(" という文字列が
# 後段フィルタとは無関係にそのまま backend の library.search() (ytmusicなら
# 実際の YouTube Music 検索API) へ渡っていたため、"(" というキーワードでの
# 実検索がネットワーク越しに実行され、"Bracket"/"P-Square" 等 "(" と何ら
# 関係の無いアーティストの楽曲・アルバムが多数ヒットして返ってしまうことを
# 確認 (即ち「無効な正規表現を指定するとエラーではなく無関係な検索結果が
# 静かに返る」というデータ破損に相当する実害。rmpc 本体
# (mierak/rmpc, rmpc-mpd/src/filter.rs `FilterKind::Regex`/`NotRegex`) は
# 検索ペインでユーザが Regex/NotRegex モードへ明示的に切り替えて生の正規表現
# 文字列を送信できる実在の機能のため、typo等で不正な正規表現を入力した
# ユーザに実際に到達しうる)。
#
# 修正方針: `_query_from_mpd_filter_expression()` が演算子種別 (`_kind`) を
# "regex" と判定した直後 (positives/negatives へ積む前、かつ backend 用
# query dict へ積む前) に `re.compile(value)` を試し、`re.error` なら
# 実 MPD と同じくコマンド全体を即座に `exceptions.MpdArgError` で中断する。
# 有効な正規表現の場合は従来通り無変更 (後段の `_mpd_track_matches_positives()`
# 等は二重チェックとして残るが、ここで弾かれた無効パターンが到達することは
# 無くなるだけで無害)。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "_mpdregexvalidate_exc"
if MARKER in s:
    print("regex filter validation already present in music_db.py, skip")
else:
    anchor = (
        '            _kind = "regex" if op in ("=~", "!~") else _MPD_POSITIVE_OP_KIND.get(op, "exact")\n'
        "            if _op_is_neg_token != _neg_wrap:\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    replacement = (
        '            _kind = "regex" if op in ("=~", "!~") else _MPD_POSITIVE_OP_KIND.get(op, "exact")\n'
        '            if _kind == "regex":\n'
        "                # 実MPD (src/song/Filter.cxx) はここでコンパイルに\n"
        "                # 失敗すると即座に例外を送出しコマンド全体をACKにする。\n"
        "                try:\n"
        "                    re.compile(value)\n"
        "                except re.error as _mpdregexvalidate_exc:\n"
        "                    raise exceptions.MpdArgError(\n"
        '                        f"Could not compile regular expression: '
        '{_mpdregexvalidate_exc}"\n'
        "                    )\n"
        "            if _op_is_neg_token != _neg_wrap:\n"
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print("patched music_db.py: invalid regex in filter expression now raises MpdArgError at parse time")
