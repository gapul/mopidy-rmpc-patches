# `_query_from_mpd_filter_expression()` (music_db.py, find/findadd/search/
# searchadd/searchaddpl/count/searchcount および current_playlist.py の
# `_pf_search()` 経由で playlistfind/playlistsearch/searchplaylist も共有) は、
# フィルタ式 `(TAG OP "VALUE")` 内の TAG が `_SEARCH_MAPPING` で解決できない
# 未知のタグ名だった場合、`if not field or not value.strip(): continue` で
# その節を黙って読み捨てるだけで、コマンド全体は成功しOKを返してしまう。
# TODO/既知の残課題を全項目消化済みのため自走エージェントが (Explore
# サブエージェントへの調査委任を経て) 新規発見した項目。
#
# 実害: dev mopidy (6601, ytmusic 実アカウント) で実際に確認 —
# `find "(Bogus == \"x\") AND (Artist == \"YOASOBI\")"` のように、有効な条件
# (Artist=="YOASOBI") と未知タグ条件を AND で同居させて送ると、未知タグの節
# だけが黙って無視され、残った条件だけで検索が実行されOKで(誤った)結果を
# 返す。同じ式が `(Bogus == "x")` 単独なら query が空になる副作用でたまたま
# ACKになるため、この非対称性がこれまで見過ごされていた。
#
# 同じファイル内の旧来の `TYPE VALUE` ペア形式 (`_query_from_mpd_search_parameters`
# の非フィルタ式分岐) は既に `field = mapping.get(...); if not field: raise
# exceptions.MpdArgError("incorrect arguments")` で未知タグを即ACKにしており、
# フィルタ式側だけがこの検証を欠いていた (同一ファイル内での非対称)。
#
# 実 MPD 仕様 (MusicPlayerDaemon/MPD を実際に clone してソース確認):
# src/song/Filter.cxx の再帰下降パーサはタグ名解決に失敗すると
# `throw FmtRuntimeError("Unknown filter type: {}", name);` を即座に送出し、
# 他の条件節の有無に関わらずコマンド全体を ACK にする (部分的な条件破棄は
# 一切行わない)。rmpc 本体 (mierak/rmpc) は `custom_query` (オプトイン設定、
# rmpc/src/config/search.rs) 有効時にユーザ入力のフィルタ式文字列をほぼ
# そのまま find/search へ渡すため、タグ名の打ち間違いがエラーにならず
# 意図と異なる結果を返してしまう実害に繋がる。
#
# 修正: 未知タグは (他の節の成否に関わらず) 即座に MpdArgError で ACK にする。
# 値が空文字列 (`(Artist == "")`) のケースは本項目のスコープ外のため無変更。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = 'raise exceptions.MpdArgError(f"Unknown filter type: {tag}")'
if MARKER in s:
    print("filter expression unknown-tag validation already present in music_db.py, skip")
else:
    anchor = (
        "            field = mapping.get(tag.lower())\n"
        "            if not field or not value.strip():\n"
        "                continue\n"
    )
    assert s.count(anchor) == 1, f"anchor count={s.count(anchor)}"
    replacement = (
        "            field = mapping.get(tag.lower())\n"
        "            if not field:\n"
        '                raise exceptions.MpdArgError(f"Unknown filter type: {tag}")\n'
        "            if not value.strip():\n"
        "                continue\n"
    )
    s = s.replace(anchor, replacement, 1)
    open(p, "w").write(s)
    print("patched music_db.py: unknown tag name in filter expression now raises MpdArgError at parse time")
