# mopidy_ytmusic/playback.py の YTMusicPlaybackProvider.last_id (library.py の
# browse() "ytmusic:watch" 分岐 = 「Similar to last played」が起点曲として使う) が、
# gapless 先読み/明示的 play() の非同期昇格待ちウィンドウ中に次曲の値で上書きされ、
# 「Aを再生中」と status/currentsong が正しく報告している間に ytmusic:watch だけが
# 既に次曲B基準のおすすめを返してしまう不具合を修正。TODO/既知の残課題を全項目消化済み
# のため自走エージェントが (general-purposeサブエージェントへの調査委任を経て) 新規発見
# した項目。
#
# 原因: translate_uri() (change_track() から同期呼び出し) が self.last_id = bId を
# 無条件に書き込む。mopidy core (mopidy/core/playback.py) は
# _on_about_to_finish() (gapless先読み) でも play()/_change() (明示的再生) でも、
# 実際に GStreamer が再生を開始し _on_stream_changed() が呼ばれて _current_tl_track
# へ昇格するより前に backend.playback.change_track() を同期呼び出しする
# (_pending_tl_track にセットしただけの段階)。このウィンドウ中は「A がまだ再生中」
# なのに translate_uri(B) が先に self.last_id を B へ書き換えてしまう。
#
# 直前のコミット (mpdaudioformatpreload-patch.py) が全く同じ呼び出し経路
# (_on_about_to_finish()→change_track()→_get_track()) で translator.py の
# 単一値ストア (_audio_format/_audio_format_uri) が次曲の値に上書きされる不具合を
# 修正済みだが、あちらは mopidy_mpd 側の status/曲メタデータ限定の修正で、
# mopidy_ytmusic/playback.py 自身の last_id には一切触れていない
# (grep "last_id" ~/.dotfiles/configs/media/mopidy/*.py は ythistory-patch.py/
# ytoauthlibraryguard-patch.py/ytsongformat-patch.py のみヒットし、いずれも
# library.py 側の読み取り箇所や uri 復元にしか触れず、playback.py の書き込み
# タイミング自体は未対応と確認済み)。つまり同じバグクラスの横展開漏れ。
#
# 対策: audio format キャッシュとは異なるアプローチを取る。last_id は「曲(uri)ごとの
# 値」ではなく「実際に再生が確定した1曲」を指す必要があるため、mopidy core 自身が
# _current_tl_track への昇格に使っているのと全く同じ仕組み
# (mopidy.audio.AudioListener の stream_changed イベント、GStreamer が実際に
# 新ストリームの再生を開始した時にのみ発火し、mopidy/core/playback.py の
# _on_stream_changed() もこれで昇格タイミングを知る) を YTMusicBackend
# (既に pykka.ThreadingActor) へ mixin し、そこで初めて last_id を確定させる。
# translate_uri() は解決した再生用URLをキーに bId を一時保持するだけに変更し
# (change_track() が直後に audio.set_uri(url) へ渡す url と同じ値なので
# stream_changed(uri) の uri と一致する)、実際に鳴り始めてから backend 側で
# self.playback.last_id へ反映する。無制限に増え続けないよう
# mpdaudioformatpreload-patch.py と同じ FIFO 方式で上限8件まで保持する。

pp = "mopidy_ytmusic/playback.py"
p = open(pp).read()

MARKER_P = "_pending_last_id"
if MARKER_P in p:
    print("playback.py already patched (pending last_id cache), skip")
else:
    OLD_INIT = (
        "        self.last_id = None\n"
        "        self.Youtube_Player_URL = None\n"
    )
    assert p.count(OLD_INIT) == 1, f"OLD_INIT count={p.count(OLD_INIT)}"
    NEW_INIT = (
        "        self.last_id = None\n"
        "        # ytlastidrace-patch.py: uri(実ストリームURL)をキーに、実際に\n"
        "        # 再生開始が確認できるまで bId を一時保持する (最大8件、FIFO)。\n"
        "        self._pending_last_id = {}\n"
        "        self.Youtube_Player_URL = None\n"
    )
    p = p.replace(OLD_INIT, NEW_INIT, 1)

    OLD_TRANSLATE = (
        "        try:\n"
        "            bId = uri.split(\":\")[2]\n"
        "            self.last_id = bId\n"
        "            return self._get_track(bId)\n"
        "        except Exception as e:\n"
        "            logger.error('translate_uri error \"%s\"', str(e))\n"
        "            return None\n"
    )
    assert p.count(OLD_TRANSLATE) == 1, f"OLD_TRANSLATE count={p.count(OLD_TRANSLATE)}"
    NEW_TRANSLATE = (
        "        try:\n"
        "            bId = uri.split(\":\")[2]\n"
        "            resolved = self._get_track(bId)\n"
        "            if resolved:\n"
        "                # last_id は backend.stream_changed() (AudioListener) が\n"
        "                # 実際の再生開始を確認してから確定させる。ここでは次曲\n"
        "                # 先読み中に現在曲のlast_idを上書きしないよう保留するだけ。\n"
        "                self._pending_last_id[resolved] = bId\n"
        "                while len(self._pending_last_id) > 8:\n"
        "                    self._pending_last_id.pop(next(iter(self._pending_last_id)))\n"
        "            return resolved\n"
        "        except Exception as e:\n"
        "            logger.error('translate_uri error \"%s\"', str(e))\n"
        "            return None\n"
    )
    p = p.replace(OLD_TRANSLATE, NEW_TRANSLATE, 1)

    open(pp, "w").write(p)
    print(
        "patched playback.py: translate_uri() が last_id を即時確定せず "
        "uri単位で一時保持するよう修正 (実再生開始まで確定を遅延)"
    )

bp = "mopidy_ytmusic/backend.py"
b = open(bp).read()

MARKER_B = "AudioListener"
if MARKER_B in b:
    print("backend.py already patched (AudioListener stream_changed), skip")
else:
    OLD_IMPORT = "from mopidy import backend\n"
    assert b.count(OLD_IMPORT) == 1, f"OLD_IMPORT count={b.count(OLD_IMPORT)}"
    NEW_IMPORT = "from mopidy import backend\nfrom mopidy.audio import AudioListener\n"
    b = b.replace(OLD_IMPORT, NEW_IMPORT, 1)

    OLD_CLASS = (
        "class YTMusicBackend(\n"
        "    pykka.ThreadingActor, backend.Backend, YTMusicScrobbleListener\n"
        "):\n"
    )
    assert b.count(OLD_CLASS) == 1, f"OLD_CLASS count={b.count(OLD_CLASS)}"
    NEW_CLASS = (
        "class YTMusicBackend(\n"
        "    pykka.ThreadingActor,\n"
        "    backend.Backend,\n"
        "    YTMusicScrobbleListener,\n"
        "    AudioListener,\n"
        "):\n"
    )
    b = b.replace(OLD_CLASS, NEW_CLASS, 1)

    OLD_ON_STOP = (
        "    def on_stop(self):\n"
        "        if self._auto_playlist_refresh_timer:\n"
        "            self._auto_playlist_refresh_timer.cancel()\n"
        "            self._auto_playlist_refresh_timer = None\n"
        "        if self._youtube_player_refresh_timer:\n"
        "            self._youtube_player_refresh_timer.cancel()\n"
        "            self._youtube_player_refresh_timer = None\n"
    )
    assert b.count(OLD_ON_STOP) == 1, f"OLD_ON_STOP count={b.count(OLD_ON_STOP)}"
    NEW_ON_STOP = (
        OLD_ON_STOP
        + "\n"
        + "    def stream_changed(self, uri):\n"
        + "        # ytlastidrace-patch.py: last_id (browse() の ytmusic:watch 分岐が\n"
        + "        # 使う「直近に再生した曲」) は、mopidy core 自身が _current_tl_track\n"
        + "        # を昇格させるのと同じ AudioListener.stream_changed イベント\n"
        + "        # (GStreamer が実際にストリーム再生を開始した時のみ発火) でのみ\n"
        + "        # 確定させる。他backend由来のuriはヒットせず素通しする。\n"
        + "        bId = self.playback._pending_last_id.pop(uri, None)\n"
        + "        if bId is not None:\n"
        + "            self.playback.last_id = bId\n"
    )
    b = b.replace(OLD_ON_STOP, NEW_ON_STOP, 1)

    open(bp, "w").write(b)
    print(
        "patched backend.py: YTMusicBackend に AudioListener を mixin し、"
        "stream_changed() で実再生開始時にのみ last_id を確定するよう修正"
    )
