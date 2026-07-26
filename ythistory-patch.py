# get_history() (Recently Played / Similar to last played が共有) が
# YTMusicServerError で丸ごと失敗し、両ブラウズが常に空になる不具合を修正。
#
# 実機 (dev mopidy 6601, ytmusic 実アカウント) で `lsinfo "YouTube Music/Recently
# Played"` / `lsinfo "YouTube Music/Similar to last played"` を実際に叩いて
# mopidy.log のトレースバックで再現・特定した:
#
#   ytmusicapi.exceptions.YTMusicServerError: None
#     File ".../ytmusicapi/mixins/library.py", line 313, in get_history
#       raise YTMusicServerError(error)
#
# ytmusicapi の get_history() (mixins/library.py) は履歴ページの各セクションが
# 必ず musicShelfRenderer を持つ前提で実装されており、1つでも別種のセクションだと
# 即 YTMusicServerError を送出して全体を失敗させる。生レスポンスをダンプして
# 実際に原因を特定したところ、このセッションでは itemSectionRenderer (中身は
# 「Sign in to view your history」という案内メッセージ、認証状態的な要因で
# セッション未確立時に混入しうるセクション種別) が該当していた。BACKLOG の
# 「Recently Played (history)」項目で先に調査済みだったが、その時点では実アカウントの
# 履歴3セクションが全て musicShelfRenderer だったため再現しないと判定されていた —
# 時間経過に伴うセッション状態の変化で、今回実機で新たに再現した。原因の細部
# (どのセクション種別が混ざるか) に関わらず、get_history() が「1つでも想定外の
# セクションがあれば全滅」という壊れやすい実装である点自体が本質的な問題のため、
# 汎用的に「musicShelfRenderer 以外は例外にせず読み飛ばす」実装に置き換える。
#
# mopidy_ytmusic.library.py の browse() は "ytmusic:history" (Recently Played) と
# "ytmusic:watch" (Similar to last played、last_id 未設定時のフォールバック) の
# 2箇所で self.backend.api.get_history() を呼んでおり、いずれも例外は try/except で
# 握りつぶされ MPD セッション自体は落ちないが、機能そのものが丸ごと空になる実害が
# ある (ytliked-patch.py 等と同種のクラス)。さらに "ytmusic:watch" 側は
# `hist[0]["videoId"]` が hist 空リストに対し未ガードで、履歴が本当に空の場合に
# IndexError で追加のトレースバックを出す (get_history() が常に例外を投げていた
# 従来は素通りしていた到達不能コードだったが、今回の修正で到達しうるようになるため
# 同じ機会に直す)。
#
# 対策: ytmusicapi のソースを差し替えることはできない (nix/lib/mopidy-env.nix の
# postPatch は mopidy-ytmusic/mopidy-mpd/mopidy-listenbrainz のみが対象で
# ytmusicapi は含まれない) ため、mopidy_ytmusic.library.py 側に get_history() 相当の
# 処理を独自実装 (musicShelfRenderer を持たないセクションは例外にせず黙ってスキップ)
# し、2箇所の呼び出しをこちらに差し替える。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "def getHistory(self):"
if MARKER in s:
    print("library.py already patched (getHistory), skip")
else:
    OLD_IMPORTS = '''from ytmusicapi.navigation import (
    NAVIGATION_BROWSE_ID,
    SECTION_LIST,
    SINGLE_COLUMN_TAB,
    TITLE_TEXT,
    nav,
)

from mopidy_ytmusic import logger'''

    NEW_IMPORTS = '''from ytmusicapi.navigation import (
    MUSIC_SHELF,
    NAVIGATION_BROWSE_ID,
    SECTION_LIST,
    SINGLE_COLUMN_TAB,
    TITLE_TEXT,
    nav,
)
from ytmusicapi.parsers.playlists import parse_playlist_items

from mopidy_ytmusic import logger'''

    assert s.count(OLD_IMPORTS) == 1, f"expected 1 occurrence of imports anchor (got {s.count(OLD_IMPORTS)})"
    s = s.replace(OLD_IMPORTS, NEW_IMPORTS, 1)

    OLD_METHOD_ANCHOR = "    def browse(self, uri):\n"
    assert s.count(OLD_METHOD_ANCHOR) == 1, f"expected 1 occurrence of browse() anchor (got {s.count(OLD_METHOD_ANCHOR)})"
    NEW_METHOD = '''    def getHistory(self):
        # ytmusicapi.get_history() は履歴セクションが1つでも musicShelfRenderer を
        # 持たない (例: musicNotifierShelfRenderer) と YTMusicServerError で
        # 全セクションもろとも失敗する。get_history() 本体と同じ browse リクエスト・
        # パース手順を踏襲しつつ、該当しないセクションだけ例外にせず読み飛ばす。
        response = self.backend.api._send_request(
            "browse", {"browseId": "FEmusic_history"}
        )
        songs = []
        for content in nav(response, SINGLE_COLUMN_TAB + SECTION_LIST):
            data = nav(content, MUSIC_SHELF + ["contents"], True)
            if not data:
                continue
            songlist = parse_playlist_items(data)
            for song in songlist:
                song["played"] = nav(content["musicShelfRenderer"], TITLE_TEXT)
            songs.extend(songlist)
        return songs

''' + OLD_METHOD_ANCHOR
    s = s.replace(OLD_METHOD_ANCHOR, NEW_METHOD, 1)

    OLD_CALL = "self.backend.api.get_history()"
    n = s.count(OLD_CALL)
    assert n == 2, f"expected 2 occurrences of get_history() call anchor (got {n})"
    s = s.replace(OLD_CALL, "self.getHistory()")

    # ytmusic:watch (Similar to last played) のフォールバック経路: 上の修正で
    # getHistory() 自体は例外を投げなくなったが、履歴が本当に空 (このアカウントに
    # 履歴が無い/全セクションがスキップされた) の場合に返る空リストへの
    # hist[0] が IndexError で未ガードのままなので、同じ機会に直す。
    OLD_HIST_INDEX = '''                elif self.backend.auth:
                    hist = self.getHistory()
                    track_id = hist[0]["videoId"]'''
    NEW_HIST_INDEX = '''                elif self.backend.auth:
                    hist = self.getHistory()
                    track_id = hist[0]["videoId"] if hist else None'''
    assert s.count(OLD_HIST_INDEX) == 1, f"expected 1 occurrence of hist[0] anchor (got {s.count(OLD_HIST_INDEX)})"
    s = s.replace(OLD_HIST_INDEX, NEW_HIST_INDEX, 1)

    open(p, "w").write(s)
    print(
        "patched library.py: get_history() が musicShelfRenderer を持たない"
        "セクションで丸ごと失敗する不具合を修正 (Recently Played / Similar to last played)"
    )
