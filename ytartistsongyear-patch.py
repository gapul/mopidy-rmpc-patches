# mopidy_ytmusic.library.py の parseSearch() (resultType=="artist" 分岐、
# artistq["songs"]["results"] 経由で曲を積む箇所) が、曲に紐づく album (song["album"]、
# ytmusicapi の parse_song_album() が返す {"name", "id"} のみで "year" キーは一度も
# 持たない) を新規 Album として登録する際、他の全ての日付欠落フォールバック (この
# ファイル内に他13箇所ある同種の unknown-date センチネル、いずれも "0000") とは異なり
# 唯一ここだけ date="1999" という無関係な決め打ち値を使っている不具合を発見。
# TODO 全項目消化済みのため自走エージェントが mopidy_ytmusic のコード品質を再調査し
# 発見した項目 (ytartistalbumyear-patch.py が同じ parseSearch() 内の album["year"]/
# single["year"] 決め打ちアクセスによる KeyError クラッシュを既に修正済みだが、この
# song["album"] 経由の箇所は KeyError にはならない――決め打ち文字列であって添字アクセス
# ではないため――ため見落とされていた別種のバグ)。
#
# 実害: `search artist "NAME"` でヒットしたアーティストの artistq["songs"]["results"]
# 経由の曲 (get_artist() のトップ曲一覧) は、実際のリリース年に関わらず常に
# Date: 1999 / AlbumDate: 1999 を返す。findadd 等でキューに積んだ後の `sort Date`や
# rmpc のアルバム年表示が実在しない偽の年で汚染される。
#
# ytmusicapi 1.12.1 (parsers/songs.py parse_song_album()) をソース確認したところ
# `return None if not flex_item else {"name": get_item_text(data, index), "id": browse_id}`
# であり、"year" キーはこの経路では構造的に一度も生成されないため .get(..., "0000")
# ではなく単純な決め打ち文字列を "0000" に修正するのが正しい対応。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'date="0000",\n                                                    musicbrainz_id="",\n                                                )\n                                            album = self.ALBUMS[song["album"]["id"]]'
if MARKER in s:
    print("library.py already patched (parseSearch artist-songs album year), skip")
else:
    OLD = (
        '                                                    date="1999",\n'
        '                                                    musicbrainz_id="",\n'
    )
    assert s.count(OLD) == 1, (
        f"expected 1 occurrence of song-album date='1999' anchor (got {s.count(OLD)})"
    )
    NEW = (
        '                                                    date="0000",\n'
        '                                                    musicbrainz_id="",\n'
    )
    s = s.replace(OLD, NEW, 1)

    open(p, "w").write(s)
    print(
        'patched library.py: parseSearch() artist分岐の song["album"] 新規登録で '
        '無関係な date="1999" 決め打ちを他箇所と同じ "0000" (unknown) フォールバックへ修正'
    )
