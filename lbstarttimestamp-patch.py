# mopidy_listenbrainz/frontend.py の ListenbrainzFrontend.track_playback_started()は
# トラック再生開始時刻を`self.last_start_time = int(time.time())`へ記録し、
# track_playback_ended()にも`self.last_start_time is None`時のフォールバック
# (`int(time.time()) - duration`)まで用意されているにもかかわらず、
# self.last_start_timeはfrontend.py内のどこからも読み出されていない(代入のみ、
# grep済み)。実際にListenBrainzへ送信される`listened_at`は
# mopidy_listenbrainz/listenbrainz.pyのsubmit_listen()が`submit_listen()`呼び出し
# 時点(=track_playback_ended()が呼ばれた時点=曲の再生完了時刻)の`int(time.time())`を
# 無条件に使っており、self.last_start_timeを受け取る引数自体が存在しない。
#
# ListenBrainzのsubmit-listens API仕様(listenbrainz.readthedocs.io/en/latest/
# users/json.html)は`listened_at`を「the time the listen started」(再生"開始"時刻)
# と明記しており、再生完了時刻ではない。この不一致は一時停止を挟んだ曲に限らず
# 全ての曲で発生する: track_playback_ended()はtrack.length分再生された後に呼ばれる
# ため、`listened_at`は常に実際の再生開始より曲の再生に要した時間だけ未来の値になる
# (一時停止を挟めばさらにその停止時間分ずれる)。ListenBrainz側の週次おすすめ生成
# ([[lbplaylistrefresh-patch]]が扱う)や時間帯別統計、他ユーザーとの再生順序比較が
# 系統的に不正確な値を基に行われてしまう。
#
# 修正: submit_listen()にlistened_at(Optional[int])引数を追加しnow_playing以外は
# 呼び出し元指定値(未指定時のみtime.time()へフォールバック)を使うよう変更、
# frontend.pyのtrack_playback_ended()呼び出し側でself.last_start_timeを渡す
# (既存のNoneフォールバックがtrack_playback_started取りこぼし時も安全な値を保証)。

import re

p1 = "mopidy_listenbrainz/listenbrainz.py"
s1 = open(p1).read()

OLD_SIG = (
    '    def submit_listen(\n'
    '        self,\n'
    '        track: str,\n'
    '        artist: str,\n'
    '        release: str = "",\n'
    '        musicbrainz_id: str = "",\n'
    '        now_playing: bool = False,\n'
    '    ) -> None:\n'
)
NEW_SIG = (
    '    def submit_listen(\n'
    '        self,\n'
    '        track: str,\n'
    '        artist: str,\n'
    '        release: str = "",\n'
    '        musicbrainz_id: str = "",\n'
    '        now_playing: bool = False,\n'
    '        listened_at: Optional[int] = None,\n'
    '    ) -> None:\n'
)

OLD_STAMP = '        if not now_playing:\n            listen["listened_at"] = int(time.time())\n'
NEW_STAMP = (
    '        if not now_playing:\n'
    '            listen["listened_at"] = (\n'
    '                listened_at if listened_at is not None else int(time.time())\n'
    '            )\n'
)

already = "listened_at: Optional[int] = None" in s1
if already:
    print("listenbrainz.py already has submit_listen(listened_at=...), skip")
else:
    assert s1.count(OLD_SIG) == 1, f"OLD_SIG count={s1.count(OLD_SIG)}"
    assert s1.count(OLD_STAMP) == 1, f"OLD_STAMP count={s1.count(OLD_STAMP)}"
    assert "from typing import" in s1 or "import typing" in s1, "typing import not found"
    s1 = s1.replace(OLD_SIG, NEW_SIG, 1)
    s1 = s1.replace(OLD_STAMP, NEW_STAMP, 1)
    if not re.search(r"^from typing import.*\bOptional\b", s1, re.MULTILINE):
        # Optional が typing から未 import なら import 行へ追加
        m = re.search(r"^from typing import (.+)$", s1, re.MULTILINE)
        assert m, "no 'from typing import ...' line found to extend"
        names = [n.strip() for n in m.group(1).split(",")]
        if "Optional" not in names:
            names.append("Optional")
            s1 = s1[: m.start()] + "from typing import " + ", ".join(names) + s1[m.end():]
    open(p1, "w").write(s1)
    print("patched listenbrainz.py: submit_listen() に listened_at 引数を追加")

p2 = "mopidy_listenbrainz/frontend.py"
s2 = open(p2).read()

OLD_CALL = (
    '        self.lb.submit_listen(\n'
    '            track=track.name or "",\n'
    '            artist=artists,\n'
    '            release=track.album and track.album.name or "",\n'
    '            musicbrainz_id=track.musicbrainz_id or "",\n'
    '        )\n'
)
NEW_CALL = (
    '        self.lb.submit_listen(\n'
    '            track=track.name or "",\n'
    '            artist=artists,\n'
    '            release=track.album and track.album.name or "",\n'
    '            musicbrainz_id=track.musicbrainz_id or "",\n'
    '            listened_at=self.last_start_time,\n'
    '        )\n'
)

if "listened_at=self.last_start_time" in s2:
    print("frontend.py already passes listened_at, skip")
else:
    assert s2.count(OLD_CALL) == 1, f"OLD_CALL count={s2.count(OLD_CALL)}"
    s2 = s2.replace(OLD_CALL, NEW_CALL, 1)
    open(p2, "w").write(s2)
    print(
        "patched frontend.py: track_playback_ended() が submit_listen() へ "
        "listened_at=self.last_start_time (曲の再生開始時刻) を渡すよう修正 "
        "(修正前は listenbrainz.py 側が呼び出し時点=曲の再生完了時刻を無条件使用)"
    )
