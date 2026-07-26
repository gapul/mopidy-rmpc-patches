# mpdsongformat-patch.py (mopidy_mpd) が追加した曲メタデータの `Format`
# (samplerate:bits:channels) フィールドへ、どの曲(uri)のものかを供給する側。
# ytaudioformat-patch.py が追加した書き込み (`_mpd_translator.set_audio_format(...)`)
# は値だけを渡しており uri を渡していなかったため、mpdsongformat-patch.py 側の
# `get_song_audio_format(uri)` が常に None を返してしまう(uri引数が無い呼び出しは
# uri=None のまま記録され、実在の曲uriと一致しないため)。
#
# 実装: _get_track(self, bId) は既に呼び出し元 translate_uri(self, uri) から
# `self.last_id = bId` として bId を受け取っているのと同じ経路で、曲の uri は
# `"ytmusic:track:" + bId` (translate_uri の `bId = uri.split(":")[2]` の逆) と
# 一意に復元できることを実装を読んで確認済み。set_audio_format 呼び出しに
# uri=f"ytmusic:track:{bId}" を追加で渡すだけで済む。

p = "mopidy_ytmusic/playback.py"
s = open(p).read()

MARKER = "uri=\"ytmusic:track:%s\""
if MARKER in s:
    print("playback.py already patched (song format uri), skip")
else:
    old = (
        "            if asr and channels:\n"
        "                from mopidy_mpd import translator as _mpd_translator\n"
        "                _mpd_translator.set_audio_format(\n"
        "                    \"%d:16:%d\" % (int(asr), int(channels))\n"
        "                )\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "            if asr and channels:\n"
        "                from mopidy_mpd import translator as _mpd_translator\n"
        "                _mpd_translator.set_audio_format(\n"
        "                    \"%d:16:%d\" % (int(asr), int(channels)),\n"
        "                    uri=\"ytmusic:track:%s\" % bId,\n"
        "                )\n"
    )
    s = s.replace(old, new, 1)
    open(p, "w").write(s)
    print("patched playback.py: set_audio_format に曲uriを付与しFormatタグを供給")
