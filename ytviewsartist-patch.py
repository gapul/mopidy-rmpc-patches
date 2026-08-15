# ytmusicapi の一部パーサ (get_history() が使う parse_playlist_items -> parse_song_artists
# -> parse_artists_runs など) は、アーティスト欄のテキストランを種別判定せずそのまま
# artist として返すため、「40K views」のような再生回数や "Song"/"Video" といった種別語が
# id なしの artist として混ざる。playlistToTracks() はそれを無条件に Artist へ変換して
# いたので、rmpc の Recently Played などでアーティスト表示・検索・list Artist が汚れる。
# 判定を1か所 (_yt_is_junk_artist) に集約し、parseSearch() の同種の除外もそれに寄せる。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

if "_yt_is_junk_artist" not in s:
    # 1) import re とヘルパを追加 (_yt_track_length_ms と同じモジュールレベル)
    helper_anchor = "class _BoundedLibraryCache(dict):"
    helper_new = '''_YT_JUNK_ARTIST_WORDS = frozenset(
    {
        "song", "video", "album", "single", "ep",
        "episode", "podcast", "station", "playlist", "profile",
    }
)
# 「40K views」「1.2M plays」「12万回視聴」など。数字始まりを必須にしているので
# Plays のような実在アーティスト名は巻き込まない。
_YT_VIEWS_RE = re.compile(
    r"^[\\d.,]+\\s*[KMBkmb万億]?\\s*(?:views?|plays?|listeners?|回視聴|回再生)$"
)


def _yt_is_junk_artist(a):
    # id を持つ artist は YTM がアーティストとして扱っているので常に本物。
    if not isinstance(a, dict) or a.get("id"):
        return False
    name = (a.get("name") or "").strip()
    if not name:
        return True
    return name.lower() in _YT_JUNK_ARTIST_WORDS or bool(_YT_VIEWS_RE.match(name))


class _BoundedLibraryCache(dict):'''
    assert s.count(helper_anchor) == 1, f"helper anchor count={s.count(helper_anchor)}"
    s = s.replace(helper_anchor, helper_new, 1)

    import_anchor = "from mopidy import backend\n"
    assert s.count(import_anchor) == 1, f"import anchor count={s.count(import_anchor)}"
    s = s.replace(import_anchor, "import re\n\n" + import_anchor, 1)

    # 2) playlistToTracks(): ゴミ artist を落とす
    pl_anchor = '''                    artists = []
                    if track.get("artists"):
                        for a in track["artists"]:
                            if not a.get("id"):
'''
    pl_new = '''                    artists = []
                    if track.get("artists"):
                        for a in track["artists"]:
                            if _yt_is_junk_artist(a):
                                continue
                            if not a.get("id"):
'''
    assert s.count(pl_anchor) == 1, f"playlistToTracks anchor count={s.count(pl_anchor)}"
    s = s.replace(pl_anchor, pl_new, 1)

    # 除外の結果 0 件になったら、artists 未取得時 (else 節) と同じ None に揃える
    empty_anchor = '''                    else:
                        artists = None

                    if "album" in track and track["album"] is not None:
'''
    empty_new = '''                    else:
                        artists = None
                    if not artists:
                        artists = None

                    if "album" in track and track["album"] is not None:
'''
    assert s.count(empty_anchor) == 1, f"empty anchor count={s.count(empty_anchor)}"
    s = s.replace(empty_anchor, empty_new, 1)

    # 3) parseSearch(): 種別語だけを見ていた既存の除外をヘルパへ統一 (song / video の2か所)
    se_anchor = '''                    for a in result.get("artists") or []:
                        if a.get("id") is None and (a.get("name") or "").strip().lower() in {
                            "song", "video", "album", "single", "ep",
                            "episode", "podcast", "station", "playlist", "profile",
                        }:
                            continue
'''
    se_new = '''                    for a in result.get("artists") or []:
                        if _yt_is_junk_artist(a):
                            continue
'''
    assert s.count(se_anchor) == 2, f"parseSearch anchor count={s.count(se_anchor)}"
    s = s.replace(se_anchor, se_new)

    open(p, "w").write(s)
    print("patched library.py: 再生回数などのゴミ artist を除外 (_yt_is_junk_artist)")
else:
    print("_yt_is_junk_artist already present, skip")
