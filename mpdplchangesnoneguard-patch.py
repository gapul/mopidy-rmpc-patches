# mpdplchangesrange-patch.py が導入した `plchanges` のバージョン一致
# (メタデータ更新のみ)分岐で、リトライループ内の範囲判定
# `if not (start <= position < end):` が `position is None` を
# ガードしておらず、TOCTOUレースで `position` が `None` になると
# `int <= None` の比較で捕捉されない `TypeError` を送出し、ACKにすら
# ならずTCP接続ごと切断されうる不具合。TODO/既知の残課題を全項目消化
# 済みのため自走エージェントが(general-purposeサブエージェントへの
# 調査委任を2段階経て)新規発見。
#
# `position = context.core.tracklist.index(tl_track).get()` は
# `mopidy/core/tracklist.py` の `index()` 実装上、`tl_track` が
# (直前の `get_current_tl_track()` 呼び出し後に別接続の `delete`/`next`
# 等で)既にトラックリストから消えていると `ValueError` を捕捉して
# `None` を返す(この関数自体のdocstringも明記する既知の仕様)。
# mpdplchangesrange-patch.py自身のコメントは「currentsongと同じTOCTOU
# レースを持つ…positionがNoneになりPos/Idがサイレントに欠落する」と
# 明記しており、ループ後のフォールバック分岐(このファイル中の
# もう1箇所、`length = context.core.tracklist.get_length().get()`
# 直後)には実際に `if position is None or not (start <= position <
# end):` という正しいガードを入れているが、同型のループ内分岐
# (version一致かつリトライ内で確定した場合)には同じガードが
# 抜けており、range引数パッチ導入時に新たに追加された比較行のみが
# 無条件で `position` を数値比較してしまう。旧実装(範囲引数を
# 受け付ける前のコード)では該当箇所は比較を経由せず直接
# `translator.track_to_mpd_format(tl_track, ..., position=position, ...)`
# を呼んでおり、`position=None` はそのまま黙って許容されていた
# (Pos:/Id:フィールドが欠落するだけ)ため、この`TypeError`は
# range引数パッチが新規に持ち込んだ回帰である。
#
# 修正: フォールバック分岐と全く同じ `position is None or` ガードを
# ループ内分岐にも追加。position が None なら(実MPDの
# `RangeArg::ClipRelaxed`と同じ「範囲外は素通り」の精神に倣い)
# 例外を投げず `None`(=このトラックについては応答なし)を返す。

cp = "mopidy_mpd/protocol/current_playlist.py"
s = open(cp).read()

old = (
    "                start, end = _mpd_plchanges_clip_range(songrange, length)\n"
    "                if not (start <= position < end):\n"
    "                    return None\n"
    "                return translator.track_to_mpd_format(\n"
)
if old not in s:
    print("plchanges None-position guard already patched, skip")
else:
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "                start, end = _mpd_plchanges_clip_range(songrange, length)\n"
        "                if position is None or not (start <= position < end):\n"
        "                    return None\n"
        "                return translator.track_to_mpd_format(\n"
    )
    s = s.replace(old, new, 1)

    open(cp, "w").write(s)
    print(
        "patched current_playlist.py: plchangesのバージョン一致分岐の"
        "リトライループ内でposition=NoneがTypeErrorとして未捕捉のまま"
        "TCP接続を切断しうる不具合を修正 (フォールバック分岐と同じ"
        "position is Noneガードを追加)"
    )
