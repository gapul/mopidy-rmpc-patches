# mopidy_ytmusic/scrobble_fe.py の YTMusicScrobbleFE.track_playback_ended() が
# duration不明(0)の曲に対してスクロブル閾値判定を実質無効化してしまう不具合を発見。
# TODO/既知の軽微な残課題を全項目消化済みのため自走エージェントが mopidy_ytmusic の
# コード品質を再調査 (ytverifytrackurl-patch.py/ytsearchuri-patch.py 等これまでの一連の
# 発見的パッチと同じ流儀) して発見した項目。
#
# 現行コード:
#   duration = track.length and track.length // 1000 or 0
#   time_position = time_position // 1000
#   if time_position < duration // 2 and time_position < 120:
#       return  # scrobbleしない
#   ...scrobbleする...
#
# 意図は「50%以上 or 120秒以上再生した場合のみscrobble」(and条件が両方成立する場合のみ
# return、つまりscrobbleは "time_position >= duration//2 OR time_position >= 120" のとき)。
# しかし track.length が None/0 (duration不明) のとき duration//2 は 0 になり、
# time_position(0以上の整数) < 0 は常に偽になるため and 全体が常に偽 → return に到達せず
# 再生時間に関わらず常にscrobbleされてしまう。
#
# duration不明は実データで起こりうる: library.py の曲パース経路 (parseSearch/
# playlistToTracks/artistToTracks 等) は duration_seconds/duration/length の全てが
# 欠落した場合 length=0 のTrackを生成する (検索結果の一部・アーティストページの
# フォールバック曲リスト・履歴の一部で発生)。
#
# 実害: rmpc等で曲を数秒だけプレビュー再生してすぐ次へスキップしても、duration不明の
# 曲は無条件で「最後まで聴いた」としてYouTube Music側の再生履歴・レコメンドへ記録
# されてしまい、意図されていた「50%再生 or 120秒再生」の閾値判定だけが
# duration不明時に完全に無効化される (enable_scrobbling 有効時に到達しうる)。
#
# 対策: duration不明時は120秒閾値のみにフォールバックする (50%判定はduration既知の
# ときだけ行う)。
p = "mopidy_ytmusic/scrobble_fe.py"
s = open(p).read()

MARKER = "long_enough = time_position >= 120"
if MARKER in s:
    print("scrobble_fe.py already patched (ytscrobblethreshold), skip")
else:
    OLD = '''                duration = track.length and track.length // 1000 or 0
                time_position = time_position // 1000

                if time_position < duration // 2 and time_position < 120:
                    logger.debug(
                        "Track not played long enough too scrobble. (50% or 120s)"
                    )
                    return'''
    NEW = '''                duration = track.length and track.length // 1000 or 0
                time_position = time_position // 1000

                if duration:
                    long_enough = time_position >= duration // 2 or time_position >= 120
                else:
                    long_enough = time_position >= 120

                if not long_enough:
                    logger.debug(
                        "Track not played long enough too scrobble. (50% or 120s)"
                    )
                    return'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of track_playback_ended anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched scrobble_fe.py: duration不明(0)の曲でscrobble閾値判定"
        "(50%再生 or 120秒再生)が常に無効化され即scrobbleされてしまう不具合を修正 "
        "(duration不明時は120秒閾値のみにフォールバック)"
    )
