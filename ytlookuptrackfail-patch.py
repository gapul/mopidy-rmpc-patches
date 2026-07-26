# mopidy_ytmusic.library.py の lookup() のうち、URIが ytmusic:track:<id> (album/artist/
# playlist のいずれのprefixにも一致しない、単曲URIの直接lookup) を解決する最後の分岐
# `return [self.getTrack(bId)]` だけが try/except による保護を持たず、getTrack() が
# 例外を投げるとそのまま呼び出し元へ伝播する不具合を発見。TODO/既知の軽微な残課題を
# 全項目消化済みのため自走エージェントが mopidy_ytmusic のコード品質を再調査
# (ytcipherfail-patch.py 等これまでの一連の発見的パッチと同じ流儀) して発見した項目。
#
# lookup() は album/artist(アップロード含む)/playlist の4分岐がいずれも
# try/except Exception: logger.exception(...) で保護されている一方、末尾の
# 「その他 (単曲URI)」分岐だけ無保護で self.getTrack(bId) を直接呼んでいる。
# browse() 側の同じ getTrack() 呼び出し (ytmusic:track: prefix分岐、526行目付近) は
# ちゃんと try/except で保護済みであり、lookup() 側だけが非対称になっている。
#
# getTrack() 内部の self.backend.api.get_song(bId) (ytmusicapi
# mixins/browsing.py) は "player" innertube エンドポイントをそのまま叩くだけで
# playabilityStatus を一切検証しない。動画が削除/非公開/地域制限で再生不能な場合、
# レスポンスに "videoDetails" キー自体が存在しないことがあり、getTrack() の
# `tv = track["videoDetails"]` が素の KeyError を投げる (加えてネットワーク瞬断等での
# get_song() 自体の例外もあり得る)。
#
# mopidy core の CoreLibrary.lookup() (mopidy/core/library.py) はこの例外を
# _backend_error_handling で最終的に捕捉するため接続断や恒久停止こそしないが、
# 「YTMusicBackend backend caused an exception」という汎用メッセージで生の
# Traceback がログに出るだけになり、どのbId/track URIが失敗したのか分からず
# デバッグが困難になる。実利用では検索結果や過去にキューへ追加した曲のURIが
# 後から削除/非公開化された場合に、`add`/`findadd`/`playlistadd` 等で単曲URIを
# 直接解決しようとするたびにこの経路を通りうる (rmpc からの「見つからない曲を
# もう一度追加しようとする」操作で実際に踏みうる)。
#
# 対策: 同じ getTrack() 呼び出しを保護している browse() 側 (526行目付近) と対称に、
# lookup() 末尾の分岐も try/except Exception で包み、失敗時は他の分岐と同じ書式で
# logger.exception して空リストへフォールバックする (呼び出し元のMPD側は他の
# 解決不能URIと同じ「0曲」として扱われ、既存の空応答ハンドリングと矛盾しない)。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'logger.exception(\'YTMusic failed to get track "%s"\', bId)'
if MARKER in s:
    print("library.py already patched (ytlookuptrackfail), skip")
else:
    OLD = '''        if (bId) in self.TRACKS:
            return [self.TRACKS[bId]]
        else:
            return [self.getTrack(bId)]
        return []'''
    NEW = '''        if (bId) in self.TRACKS:
            return [self.TRACKS[bId]]
        else:
            try:
                return [self.getTrack(bId)]
            except Exception:
                logger.exception('YTMusic failed to get track "%s"', bId)
        return []'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of lookup() track-branch anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: lookup()の単曲URI直接解決分岐(getTrack()呼び出し)を "
        "try/exceptで保護し、削除/非公開/地域制限等で再生不能な動画のget_song()失敗が "
        "汎用エラーとしてしか記録されずbId特定が困難になる不具合を修正"
    )
