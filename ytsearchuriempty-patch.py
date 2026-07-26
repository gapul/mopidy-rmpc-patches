# mopidy_ytmusic.library.py の search() の "uri" 分岐 (ytsearchuri-patch.py が
# lookup() 委譲へ書き換え済み) が `uri = query["uri"][0]` と無条件にインデックス
# アクセスしており、query["uri"] が空リストの場合 IndexError (LookupError の
# サブクラス) を送出する不具合。TODO/既知の軽微な残課題を全項目消化済みのため
# 自走エージェントが Explore サブエージェントに未パッチ・薄くしか監査されていない
# 領域の横断調査を委任し新規発見した項目。
#
# mopidy.core.LibraryController.search() は validation.check_query() で
# query の値を検証するが、`_check_iterable()` は空リストを正当な値として
# 通過させる (文字列でもイテレータでもない通常のリストのため)。さらに
# search() 自身が `reraise = (TypeError, LookupError)` を指定して
# _backend_error_handling() の一般 Exception 握り潰しから TypeError と
# LookupError (IndexError含む) を意図的に除外している (呼び出し側で
# "exact引数非対応" 検出用に TypeError だけを捕捉する設計だが、LookupError
# 側の呼び出し元での捕捉が無い)。結果として `core.library.search()` を
# `{"uri": []}` で呼ぶと mopidy_ytmusic 側の IndexError が握り潰されずに
# 呼び出し元まで伝播する。
#
# MPD テキストプロトコル自身の `find file ""`/`search filename ""` は
# mopidy_mpd/protocol/music_db.py の `_query_from_mpd_search_parameters()`
# が `value.strip()` が真の値のみを query に積むため空リストを作れず影響を
# 受けないが、mopidy-http 等が公開する HTTP JSON-RPC (`core.library.search`
# メソッドへ `{"query": {"uri": []}}` を直接渡す呼び出し) からは到達可能で、
# lbgetitems-patch.py 等がこれまでも前提としてきた「HTTP JSON-RPC も正当な
# 攻撃/入力面」の同じ経路。JSON-RPC ディスパッチャ自体は例外を
# JsonRpcApplicationError に変換するため mopidy プロセス自体は生存するが、
# 本来 ValidationError 相当の穏当なエラーで済むべきところ生の IndexError の
# トレースバックが漏れてしまう。
#
# 対策: 他の分岐 (unresolvable uri scheme) と同じ「対象外なら None を返す」
# という既存の設計に合わせ、query["uri"] が空なら [0] へアクセスする前に
# None を返す。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = 'elif "uri" in query:\n            if not query["uri"]:\n                return None\n            uri = query["uri"][0]'
if MARKER in s:
    print("library.py already patched (search uri-branch empty-list guard), skip")
else:
    OLD = '''        elif "uri" in query:
            uri = query["uri"][0]
            if uri.startswith("ytmusic:"):'''
    NEW = '''        elif "uri" in query:
            if not query["uri"]:
                return None
            uri = query["uri"][0]
            if uri.startswith("ytmusic:"):'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of search() uri-branch anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: search()のuri分岐にquery[\"uri\"]空リストガードを追加し、"
        "core.library.search({\"uri\": []})経由のIndexError未捕捉伝播を解消"
    )
