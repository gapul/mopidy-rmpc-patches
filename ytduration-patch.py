# mopidy_ytmusic.library.py の playlistToTracks()/albumToTracks()/parseSearch() が
# 曲の長さ (length, ms) を "MM:SS" 前提で自前パースしており、1時間を超える動画
# (YouTube Music では DJ ミックス/作業用BGM/睡眠導入音/ポッドキャスト的な長尺コンテンツが
# 珍しくなく、Liked Songs・プレイリスト・アルバム・検索結果いずれにも実データで
# 混在しうる) の "H:MM:SS" 表記に対して不具合を持つことを発見。TODO 全項目消化済みの
# ため自走エージェントが rmpc 側の未実装コマンド調査 (新規ギャップなしと確認済み) に
# 続き、ytartistcache-patch.py までの一連のパッチが同種のバグを発見してきた実績を
# 踏まえ mopidy_ytmusic のコード品質を再調査して発見した項目。
#
# ytmusicapi 1.12.1 (parsers/_utils.py parse_duration、parsers/songs.py
# parse_song_runs) を実際にソース確認したところ、ytmusicapi 自身は
# duration文字列と対で "duration_seconds" (H:MM:SS を正しく解釈した秒数、
# mixins/browsing.py get_album のdocstring例で `"duration_seconds": 4657`
# (=1時間17分37秒) が実例として明記されている) を既に計算済みで track dict に
# 含めている (playlistToTracks/parseSearchが受け取るtrackはいずれも内部で
# parse_song_runs/parse_playlist_items を経由するため一貫して存在する)。
# ところが mopidy_ytmusic 側はこれを一切使わず、以下3箇所で独自に
# `文字列.split(":")` した結果の [0]/[1] 要素だけを「分:秒」として決め打ちで
# 使っており、"H:MM:SS" ("1:02:03" 等) では時間成分を無視して分:秒だけを
# length として計算してしまう (実際の3723秒ではなく62秒になる等、静かに
# 大幅に短い長さが返る):
#
# (1) playlistToTracks(): `duration = (...).split(":")` を例外処理無しで
#     `int(duration[0])*60000 + int(duration[1])*1000` に使用。
# (2) albumToTracks(): `length = [int(i) for i in song["duration"].split(":")]`
#     (ValueErrorのみ捕捉、フォールバックは`[0, 0]`) を同様に使用。加えて
#     duration文字列がコロン無しの単一要素 (例: "45") の場合、split結果が
#     1要素になり ValueError は発生しないため except節に落ちず、直後の
#     `length[1]` で未捕捉の IndexError が発生しクラッシュしうる
#     (呼び出し元 browse()/lookup()/search() の try/except Exception で
#     セッションは落ちないが、該当アルバム全体が結果から欠落する)。
# (3) parseSearch(): `length = [int(i) for i in (result.get("duration") or
#     "0:00").split(":")]` も同様の実装・同様の未捕捉 IndexError の懸念。
#
# 対策: ytmusicapi が既に計算済みの "duration_seconds" を優先し (H:MM:SS を
# 正しく反映)、無い場合のみ任意の桁数のコロン区切り文字列を汎用的に
# (ytmusicapi の parse_duration と同じ乗算累積方式で) 解釈するヘルパーを
# 追加してこの3箇所を置き換える (IndexErrorの懸念も併せて解消)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "def _yt_track_length_ms(track):"
if MARKER in s:
    print("library.py already patched (duration), skip")
else:
    OLD_IMPORT_ANCHOR = "from mopidy_ytmusic import logger\n\n\nclass YTMusicLibraryProvider(backend.LibraryProvider):"
    NEW_IMPORT_ANCHOR = '''from mopidy_ytmusic import logger


def _yt_track_length_ms(track):
    # ytmusicapi が計算済みの秒数 (H:MM:SS を正しく解釈済み) を優先する。
    duration_seconds = track.get("duration_seconds")
    if isinstance(duration_seconds, (int, float)):
        return int(duration_seconds * 1000)
    text = track.get("duration") or track.get("length")
    if not text:
        return 0
    try:
        parts = [int(p) for p in str(text).split(":")]
    except ValueError:
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds * 1000


class YTMusicLibraryProvider(backend.LibraryProvider):'''

    assert s.count(OLD_IMPORT_ANCHOR) == 1, (
        f"expected 1 occurrence of import anchor (got {s.count(OLD_IMPORT_ANCHOR)})"
    )
    s = s.replace(OLD_IMPORT_ANCHOR, NEW_IMPORT_ANCHOR, 1)

    # (1) playlistToTracks()
    OLD_PLS_ASSIGN = '''                duration = ["0", "0"]
                if "duration" in track or "length" in track:
                    duration = (
                        track["duration"]
                        if "duration" in track
                        else track["length"]
                    ).split(":")
                artists = []'''
    NEW_PLS_ASSIGN = '''                track_length_ms = _yt_track_length_ms(track)
                artists = []'''
    assert s.count(OLD_PLS_ASSIGN) == 1, (
        f"expected 1 occurrence of playlistToTracks duration-assign anchor (got {s.count(OLD_PLS_ASSIGN)})"
    )
    s = s.replace(OLD_PLS_ASSIGN, NEW_PLS_ASSIGN, 1)

    OLD_PLS_USE = '''                        length=(
                            int(duration[0]) * 60000 + int(duration[1]) * 1000
                        ),'''
    NEW_PLS_USE = "                        length=track_length_ms,"
    assert s.count(OLD_PLS_USE) == 1, (
        f"expected 1 occurrence of playlistToTracks duration-use anchor (got {s.count(OLD_PLS_USE)})"
    )
    s = s.replace(OLD_PLS_USE, NEW_PLS_USE, 1)

    # (2) albumToTracks()
    OLD_ALB_ASSIGN = '''            # if song["videoId"] not in self.TRACKS:
            try:
                length = [int(i) for i in song["duration"].split(":")]
            except ValueError:
                length = [0, 0]
            # Annoying workaround for Various Artists'''
    NEW_ALB_ASSIGN = '''            # if song["videoId"] not in self.TRACKS:
            song_length_ms = _yt_track_length_ms(song)
            # Annoying workaround for Various Artists'''
    assert s.count(OLD_ALB_ASSIGN) == 1, (
        f"expected 1 occurrence of albumToTracks duration-assign anchor (got {s.count(OLD_ALB_ASSIGN)})"
    )
    s = s.replace(OLD_ALB_ASSIGN, NEW_ALB_ASSIGN, 1)

    # 先頭に改行を含めて完全に一行を固定し、parseSearch側の32スペース版
    # (同じ末尾テキストを持つが16スペース版が部分文字列として埋め込まれてしまう)
    # と誤ってマッチしないようにする。
    OLD_ALB_USE = "\n                length=(length[0] * 60 * 1000) + (length[1] * 1000),"
    NEW_ALB_USE = "\n                length=song_length_ms,"
    assert s.count(OLD_ALB_USE) == 1, (
        f"expected 1 occurrence of albumToTracks duration-use anchor (got {s.count(OLD_ALB_USE)})"
    )
    s = s.replace(OLD_ALB_USE, NEW_ALB_USE, 1)

    # (3) parseSearch() (song branch)
    OLD_SEARCH_ASSIGN = '''                        try:
                            length = [int(i) for i in (result.get("duration") or "0:00").split(":")]
                        except ValueError:
                            length = [0, 0]
                        if result["videoId"] is None:'''
    NEW_SEARCH_ASSIGN = '''                        track_length_ms = _yt_track_length_ms(result)
                        if result["videoId"] is None:'''
    assert s.count(OLD_SEARCH_ASSIGN) == 1, (
        f"expected 1 occurrence of parseSearch duration-assign anchor (got {s.count(OLD_SEARCH_ASSIGN)})"
    )
    s = s.replace(OLD_SEARCH_ASSIGN, NEW_SEARCH_ASSIGN, 1)

    OLD_SEARCH_USE = "                                length=(length[0] * 60 * 1000) + (length[1] * 1000),"
    NEW_SEARCH_USE = "                                length=track_length_ms,"
    assert s.count(OLD_SEARCH_USE) == 1, (
        f"expected 1 occurrence of parseSearch duration-use anchor (got {s.count(OLD_SEARCH_USE)})"
    )
    s = s.replace(OLD_SEARCH_USE, NEW_SEARCH_USE, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: playlistToTracks/albumToTracks/parseSearch の曲長パースが "
        "H:MM:SS (1時間超) を切り捨てる不具合、および albumToTracks/parseSearch の "
        "コロン無しduration文字列での未捕捉IndexErrorを修正 (ytmusicapiのduration_seconds優先)"
    )
