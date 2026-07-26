# mopidy_ytmusic の設定 verify_track_url (ext.conf: `verify_track_url = yes`、
# __init__.py で config.Boolean(optional=True) として宣言、backend.py の __init__ で
# self.verify_track_url へ読み込み済み) が、実際には playback.py のどこからも
# 参照されておらず完全な死に設定になっている不具合。TODO/既知の軽微な残課題を
# 全項目消化済みのため自走エージェントが mopidy_ytmusic のコード品質を再調査
# (ytcipherfail-patch.py 等これまでの一連の発見的パッチと同じ流儀) して発見した項目。
#
# アップストリーム (github.com/OzymandiasTheGreat/mopidy-ytmusic, pytube ベースの
# 素の _get_track()) では、ストリームURL解決の最後に
#     if self.backend.verify_track_url and requests.head(url).status_code == 403:
#         # 署名(cipher)が壊れて誤って復号されたURLである可能性が高い
#         logger.error(...); self.backend._youtube_player_refresh_timer.now(); return None
#     else:
#         return url
# という「実際にURLが403で弾かれていないか確認してから返す」ガードが存在していた
# (gh api repos/OzymandiasTheGreat/mopidy-ytmusic/contents/mopidy_ytmusic/playback.py
# で実際にアップストリームソースを取得し確認)。ytdlp-patch.py が pytube 由来の cipher
# 解読が壊れる問題を回避するため _get_track() を yt-dlp 委譲へ全面書き換えした際に、
# このガード節ごと丸ごと削除され、以後 verify_track_url の値がどう変わっても
# 一切の副作用が無いまま今日に至っていた (config schema にも ext.conf にも残っている
# ため、設定した本人には効いているように見える点が特に紛らわしい)。
#
# 実害: yt-dlp が解決した googlevideo.com の直リンクは、IP不一致・レート制限・
# 期限切れ等で実際には 403 を返す個体が稀に混じる (yt-dlp 自身の内部検証はダウンロード
# 実行時のものであり extract_info(download=False) の時点では叩かれない)。verify_track_url
# を有効にしていても実際には何も確認されないため、そのような URL がそのまま
# translate_uri() の戻り値として GStreamer に渡り、再生開始に失敗する。ユーザから見ると
# 「なぜか曲が再生されない」だけで mopidy.log にも verify_track_url に関するヒントは
# 何も残らない。
#
# 対策: yt-dlp 側のフローに合わせ、URL解決成功後 (asr/audio_channels 記録の直前) に
# self.backend.verify_track_url が真なら HEAD リクエストで実際に 403 を返さないか確認する。
# 403ならログを残し None を返して呼び出し元 (translate_uri) に「解決失敗」として扱わせる
# (アップストリームの意図と対称)。HEAD自体が例外を投げた場合 (タイムアウト・DNS失敗等、
# verify_track_url の検査自体の問題であって曲が実際に再生不能とは限らない) はログのみで
# 握りつぶし通常どおり再生を試みる (verify_track_url 無効時と同じ挙動へフォールバック、
# 誤検知で再生機会を奪わない)。yt-dlp は独自にcipherを解読するため
# self.backend._youtube_player_refresh_timer.now() (pytube cipher劣化時の自己修復) は
# 今の構成には適用できず、この呼び出しは移植しない。

p = "mopidy_ytmusic/playback.py"
s = open(p).read()

MARKER = "verify_track_url check failed"
if MARKER in s:
    print("playback.py already patched (verify_track_url), skip")
else:
    OLD = '''        if url is None:
            logger.error("YTMusic yt-dlp: no url for %s", bId)
            return None
        try:
            asr = info.get("asr")'''
    NEW = '''        if url is None:
            logger.error("YTMusic yt-dlp: no url for %s", bId)
            return None
        if self.backend.verify_track_url:
            try:
                verify = requests.head(url, timeout=5, allow_redirects=True)
            except Exception:
                logger.debug(
                    "YTMusic: verify_track_url check failed for %s, proceeding anyway",
                    bId,
                    exc_info=True,
                )
            else:
                if verify.status_code == 403:
                    logger.error(
                        "YTMusic yt-dlp resolved URL for %s returned 403 Forbidden, "
                        "treating as unplayable",
                        bId,
                    )
                    return None
        try:
            asr = info.get("asr")'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of _get_track url-resolved anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched playback.py: verify_track_url が死に設定だった不具合を修正。"
        "yt-dlp解決後のURLをHEADで実検証し403なら再生失敗として扱うガードを復元"
    )
