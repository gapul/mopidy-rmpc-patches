# find/search/count/searchcount/findadd/searchadd/searchaddpl/list/
# playlistfind/playlistsearch/searchplaylist が共有するフィルタ式パーサ
# `_query_from_mpd_filter_expression` (music_db.py) のクオート値抽出ループが、
# VALUE の長さに一切上限を設けていない不具合を修正。TODO/既知の残課題を
# 全項目消化済みのため自走エージェントが (general-purpose サブエージェントへの
# 調査委任を経て) 新規発見。
#
# 実MPD本体を gh raw (raw.githubusercontent.com/MusicPlayerDaemon/MPD/master)
# で直接確認 (要約ではなく生のC++ソース):
#   - src/song/Filter.cxx ExpectQuoted(): クオート文字列を1バイトずつ
#     `char buffer[4096]` へ積んでいき、`length >= sizeof(buffer)` (4096バイト
#     到達) で `throw std::runtime_error("Quoted value is too long")`。この
#     関数は `(TAG OP "VALUE")` 形式のフィルタ式構文専用のクオート値パーサで、
#     `ParseStringFilter()`/`SongFilter::Parse()` から呼ばれ、find/search/
#     count/searchcount/findadd/searchadd/searchaddpl/list/playlistfind/
#     playlistsearch の全ハンドラ (DatabaseCommands.cxx/QueueCommands.cxx) が
#     経由する。例外は `ACK_ERROR_ARG`(2) としてそのままクライアントへ返る。
#   - 旧式構文 `find TAG VALUE` の VALUE は既にコマンドライン全体の
#     トークナイザ (Tokenizer.cxx) が別途処理済みの引数であり ExpectQuoted は
#     通らないため、この4096バイト上限はフィルタ式構文のクオート値専用
#     (旧式構文は対象外、本パッチも旧式構文には手を入れない)。
#
# mopidy_mpd 側の `_query_from_mpd_filter_expression` (mpdsearch-patch.py が
# 導入したクオート値抽出ループ、`buf = []` から `value = "".join(buf)` まで)
# は文字を1つずつ `buf` へ積むだけで長さチェックが一切無く、任意長の
# クオート値を無制限に受理してしまう。current_playlist.py はこの関数を
# `from mopidy_mpd.protocol.music_db import _query_from_mpd_filter_expression`
# で直接再利用 (独自複製ではない) しているため、music_db.py 側の1箇所を
# 直すだけで playlistfind/playlistsearch/searchplaylist にも自動的に伝播する。
#
# BACKLOG.md 全体を "too long"/"4096"/"4095"/"Quoted value" で検索したが
# 既出は無く、多数あるフィルタ式関連パッチ (mpdfilterexprtrailing/
# mpdfilterkind/mpdfilteremptyvalue/mpdfilterwhitespacevalue/mpdfiltercsci/
# mpdnegexpr/mpdnegfilter/mpdnegonlyfilter/mpdnegcompound/mpdregexvalidate/
# mpdsincefilter/mpdbasefilter/mpdaudioformatfilter/mpdpriofilter(valuestrict)/
# mpdfindexactfilter/mpdfindmultitag/mpdfilterexprtagerr) のいずれもVALUEの
# 長さは扱っていないことを確認済み。
#
# 修正方針: クオート値抽出ループ内で1文字追加する都度、実MPDの
# `buffer[length++] = *s++; if (length >= sizeof(buffer)) throw` と同じ
# タイミング (バイト追加直後) で UTF-8 バイト長を判定し、4096バイト到達で
# `exceptions.MpdArgError("Quoted value is too long")` を送出する
# (real MPDはワイヤ上の生バイト列を数えるため、mopidy_mpd側でも文字数では
# なくUTF-8エンコード後のバイト長で判定し実MPDの挙動に近づける)。
#
# 実機確認 (TCP 6601、mopidy-ytmusic 実アカウント):
#   `find "(Artist == \"` + "A"*5000 + `\")"` (5000バイトのクオート値) が
#   修正前は `OK` (0件、無制限に受理) だったが、修正後は
#   `ACK [2@0] {find} Quoted value is too long` に変化することを確認。
#   同じ5000バイト値を `search`/`count`/`list album (...)` でも同様に
#   ACKへ変化することを確認。`clear`+`findadd "(Artist == \"YOASOBI\")"`で
#   実データを積んだ後の `playlistfind "(Artist == \"` + "A"*5000 + `\")"`も
#   同様にACKへ変化 (current_playlist.py 経由での伝播を確認)。
#   回帰確認: 4000バイトの値 (上限未満) は修正前後とも `OK` で変化なし、
#   境界値 4095バイト (`OK`) / 4096バイト (`ACK`) がちょうど閾値どおりに
#   切り替わることを確認、マルチバイト文字 (全角/絵文字含む) を混ぜた値も
#   UTF-8バイト長基準で同じ閾値になることを確認、通常の短い
#   `find "(Artist == \"YOASOBI\")"` (22件) は無変更、mopidy.log に新規
#   ERROR/Traceback 0件、mopidy が正常に起動し続けることを確認。

p = "mopidy_mpd/protocol/music_db.py"
s = open(p).read()

MARKER = "mpdfiltervaluelength-patch"
if MARKER in s:
    print("filter-expression quoted value length limit already present in music_db.py, skip")
else:
    old_loop = (
        "        quote = expr[qpos]\n"
        "        j = qpos + 1\n"
        "        buf = []\n"
        "        while j < L:\n"
        "            c = expr[j]\n"
        '            if c == "\\\\" and j + 1 < L:\n'
        "                buf.append(expr[j + 1])\n"
        "                j += 2\n"
        "                continue\n"
        "            if c == quote:\n"
        "                break\n"
        "            buf.append(c)\n"
        "            j += 1\n"
        '        value = "".join(buf)\n'
    )
    assert s.count(old_loop) == 1, f"old_loop count={s.count(old_loop)}"
    new_loop = (
        "        quote = expr[qpos]\n"
        "        j = qpos + 1\n"
        "        buf = []\n"
        "        # mpdfiltervaluelength-patch: 実MPD (Filter.cxx ExpectQuoted) の\n"
        "        # `char buffer[4096]`+`length >= sizeof(buffer)`と同じタイミングで\n"
        "        # UTF-8バイト長を判定し、4096バイト到達で`Quoted value is too long`\n"
        "        # へACKする (real MPDはワイヤ上の生バイト列を数えるため文字数では\n"
        "        # なくUTF-8バイト長で判定)。\n"
        "        _mpdfiltervaluelength_bytes = 0\n"
        "        while j < L:\n"
        "            c = expr[j]\n"
        '            if c == "\\\\" and j + 1 < L:\n'
        "                _ch = expr[j + 1]\n"
        "                j += 2\n"
        "            else:\n"
        "                if c == quote:\n"
        "                    break\n"
        "                _ch = c\n"
        "                j += 1\n"
        "            buf.append(_ch)\n"
        '            _mpdfiltervaluelength_bytes += len(_ch.encode("utf-8"))\n'
        "            if _mpdfiltervaluelength_bytes >= 4096:\n"
        '                raise exceptions.MpdArgError("Quoted value is too long")\n'
        '        value = "".join(buf)\n'
    )
    s = s.replace(old_loop, new_loop, 1)

    open(p, "w").write(s)
    print("patched music_db.py: フィルタ式クオート値に実MPD同等の4096バイト上限を追加")
