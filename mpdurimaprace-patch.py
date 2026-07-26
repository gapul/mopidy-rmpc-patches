# mopidy_mpd/uri_mapper.py の MpdUriMapper インスタンスは actor.py で1個だけ生成され
# (`self.uri_map = uri_mapper.MpdUriMapper(core)`)、network.py の `Server` が
# `protocol_kwargs={"uri_map": self.uri_map, ...}` として保持したまま、新しい
# クライアント接続 (`Connection`) が来るたびに同じ dict をそのまま
# `self.protocol.start(self, **self.protocol_kwargs)` へ渡して `MpdSession`
# (`pykka.ThreadingActor` = 実OSスレッド) を起動する。つまり **全クライアント接続が
# 同一の MpdUriMapper インスタンス、ひいては同一の `_uri_from_name` /
# `_browse_name_from_uri` / `_playlist_name_from_uri` dict を、一切のロック無しで
# 各自のスレッドから直接読み書きしている**。TODO/既知の残課題を全項目消化済みのため
# 自走エージェントが mopidy_mpd のコード品質を再調査して発見した。
#
# mpdplaylistcache-patch.py / mpdbrowsecache-patch.py / mpdplaylistnamerace-patch.py は
# この3つの dict の「stale purge」「KeyError化」といったロジック面の不具合は修正済み
# だが、いずれも「単一スレッドの逐次実行」を前提にしており、複数クライアントが
# 同時にブラウズ/プレイリスト一覧操作を行った場合の**スレッド安全性**は一切考慮
# されていなかった。
#
# 実害: `refresh_browse_children()` は
#   for path, uri in self._uri_from_name.items()
# という dict の内容をその場で走査するリスト内包表記、`refresh_playlists_mapping()` は
#   stale_uris = set(self._playlist_name_from_uri) - current_uris
# という dict キー集合のスナップショット構築を行う。CPython の dict は「走査中に
# 要素数が変化する(挿入/削除)」と `RuntimeError: dictionary changed size during
# iteration` を送出する仕様のため、あるクライアント接続のスレッドがこれらの走査を
# 実行している最中に、**別のクライアント接続**のスレッドが `dispatcher.py` 経由で
# `insert()` (browse()中の子要素登録、または `refresh_playlists_mapping()` 自身の
# 更新ループ) を呼んで同じ dict へ挿入/削除を行うと、走査側スレッドで
# `RuntimeError` が飛ぶ。`RuntimeError` は `exceptions.MpdAckError` のサブクラス
# ではないため `dispatcher.py` の `_catch_mpd_ack_errors_filter` に捕捉されず、
# `session.py` にも保護が無いため pykka アクターの外まで伝播し
# `network.LineProtocol.on_failure` (`self.connection.stop("Actor failed.")`) に
# 到達、ACK エラーが一切返らずその接続の TCP セッションが問答無用で切断される。
# トリガ条件は「2本以上の MPD 接続が同時に張られている」だけで良く (rmpc + 別の
# rmpc インスタンス/他の MPD クライアント/本パッチの検証ハーネス自身など)、一方が
# `lsinfo`/`listall`/`listallinfo`/`listfiles` 等でブラウズ中、もう一方が
# `listplaylists`/`rm`/`rename`/`save` 等でプレイリスト名前空間を更新する、という
# ごくありふれた並行操作で発現する。
#
# 修正: `MpdUriMapper.__init__` に `threading.RLock()` を持たせ、3つの dict を
# 直接読み書きする箇所 (`insert()` 全体、`refresh_browse_children()` の走査+purge、
# `refresh_playlists_mapping()` の stale purge+insert ループ) を `with self._lock:`
# で保護する。RLock (再入可能ロック) を使うのは、`refresh_playlists_mapping()` の
# ロック区間内から (同一スレッドで) `insert()` を呼び出すため。`listall` 系の
# 既知のブロッキング事故 (BACKLOG.md 記載の mpdlistall-patch.py revert 事案:
# core actor を長時間専有すると他クライアントの `status` すら固まる) を教訓に、
# `refresh_playlists_mapping()` 内の `self.core.playlists.as_list().get()`
# (バックエンドへの実ネットワーク呼び出しを伴いうる pykka future の `.get()`) は
# ロックの**外**で実行し、ロックは「ローカルの dict 操作」だけに最小化して、他の
# クライアント接続がこの呼び出しの完了を待たされる時間を増やさないようにする。

p = "mopidy_mpd/uri_mapper.py"
s = open(p).read()

MARKER = "self._lock = threading.RLock()"
if MARKER in s:
    print("mpdurimaprace already applied to uri_mapper.py, skip")
else:
    # 1) import threading + __init__ で RLock を保持
    old_init = (
        "import re\n"
        "\n"
        "# TOOD: refactor this into a generic mapper that does not know about browse\n"
        "# or playlists and then use one instance for each case?\n"
        "\n"
        "\n"
        "class MpdUriMapper:\n"
        "\n"
        '    """\n'
        "    Maintains the mappings between uniquified MPD names and URIs.\n"
        '    """\n'
        "\n"
        "    #: The Mopidy core API. An instance of :class:`mopidy.core.Core`.\n"
        "    core = None\n"
        "\n"
        '    _invalid_browse_chars = re.compile(r"[\\n\\r]")\n'
        '    _invalid_playlist_chars = re.compile(r"[/]")\n'
        "\n"
        "    def __init__(self, core=None):\n"
        "        self.core = core\n"
        "        self._uri_from_name = {}\n"
        "        self._browse_name_from_uri = {}\n"
        "        self._playlist_name_from_uri = {}\n"
    )
    assert s.count(old_init) == 1, f"old_init count={s.count(old_init)}"
    new_init = (
        "import re\n"
        "import threading\n"
        "\n"
        "# TOOD: refactor this into a generic mapper that does not know about browse\n"
        "# or playlists and then use one instance for each case?\n"
        "\n"
        "\n"
        "class MpdUriMapper:\n"
        "\n"
        '    """\n'
        "    Maintains the mappings between uniquified MPD names and URIs.\n"
        '    """\n'
        "\n"
        "    #: The Mopidy core API. An instance of :class:`mopidy.core.Core`.\n"
        "    core = None\n"
        "\n"
        '    _invalid_browse_chars = re.compile(r"[\\n\\r]")\n'
        '    _invalid_playlist_chars = re.compile(r"[/]")\n'
        "\n"
        "    def __init__(self, core=None):\n"
        "        self.core = core\n"
        "        self._uri_from_name = {}\n"
        "        self._browse_name_from_uri = {}\n"
        "        self._playlist_name_from_uri = {}\n"
        "        # 1個のMpdUriMapperインスタンスを全クライアント接続(各々別スレッドの\n"
        "        # MpdSessionアクター)が共有するため、上記3つのdictへの読み書きは\n"
        "        # RLockで直列化する(mpdurimaprace-patch.py)。\n"
        "        self._lock = threading.RLock()\n"
    )
    s = s.replace(old_init, new_init, 1)

    # 2) insert(): 全体をロックで保護 (他クライアントとの同時挿入/走査からの直列化)
    old_insert = (
        "    def insert(self, name, uri, playlist=False):\n"
        '        """\n'
        "        Create a unique and MPD compatible name that maps to the given URI.\n"
        '        """\n'
        "        name = self._create_unique_name(name, uri)\n"
        "        self._uri_from_name[name] = uri\n"
        "        if playlist:\n"
        "            self._playlist_name_from_uri[uri] = name\n"
        "        else:\n"
        "            self._browse_name_from_uri[uri] = name\n"
        "        return name\n"
    )
    assert s.count(old_insert) == 1, f"old_insert count={s.count(old_insert)}"
    new_insert = (
        "    def insert(self, name, uri, playlist=False):\n"
        '        """\n'
        "        Create a unique and MPD compatible name that maps to the given URI.\n"
        '        """\n'
        "        with self._lock:\n"
        "            name = self._create_unique_name(name, uri)\n"
        "            self._uri_from_name[name] = uri\n"
        "            if playlist:\n"
        "                self._playlist_name_from_uri[uri] = name\n"
        "            else:\n"
        "                self._browse_name_from_uri[uri] = name\n"
        "            return name\n"
    )
    s = s.replace(old_insert, new_insert, 1)

    # 3) refresh_browse_children(): 走査+purgeをロックで保護
    old_browse = (
        "        prefix = base_path + \"/\"\n"
        "        stale_paths = [\n"
        "            path\n"
        "            for path, uri in self._uri_from_name.items()\n"
        "            if path.startswith(prefix)\n"
        '            and "/" not in path[len(prefix) :]\n'
        "            and uri not in current_uris\n"
        "        ]\n"
        "        for path in stale_paths:\n"
        "            stale_uri = self._uri_from_name.pop(path)\n"
        "            if self._browse_name_from_uri.get(stale_uri) == path:\n"
        "                del self._browse_name_from_uri[stale_uri]\n"
    )
    assert s.count(old_browse) == 1, f"old_browse count={s.count(old_browse)}"
    new_browse = (
        "        prefix = base_path + \"/\"\n"
        "        with self._lock:\n"
        "            stale_paths = [\n"
        "                path\n"
        "                for path, uri in self._uri_from_name.items()\n"
        "                if path.startswith(prefix)\n"
        '                and "/" not in path[len(prefix) :]\n'
        "                and uri not in current_uris\n"
        "            ]\n"
        "            for path in stale_paths:\n"
        "                stale_uri = self._uri_from_name.pop(path)\n"
        "                if self._browse_name_from_uri.get(stale_uri) == path:\n"
        "                    del self._browse_name_from_uri[stale_uri]\n"
    )
    s = s.replace(old_browse, new_browse, 1)

    # 4) refresh_playlists_mapping(): as_list().get()はロック外(listall事案の教訓で
    #    core actor待ちの間に他クライアントを長時間ブロックしないため)、
    #    dictのpurge+insertループだけをロックで保護
    old_refresh = (
        "        playlist_refs = [\n"
        "            ref for ref in self.core.playlists.as_list().get() if ref.name\n"
        "        ]\n"
        "        current_uris = {ref.uri for ref in playlist_refs}\n"
        "\n"
        "        stale_uris = set(self._playlist_name_from_uri) - current_uris\n"
        "        for uri in stale_uris:\n"
        "            stale_name = self._playlist_name_from_uri.pop(uri)\n"
        "            if self._uri_from_name.get(stale_name) == uri:\n"
        "                del self._uri_from_name[stale_name]\n"
        "\n"
        "        for playlist_ref in playlist_refs:\n"
        '            name = self._invalid_playlist_chars.sub("|", playlist_ref.name)\n'
        "            self.insert(name, playlist_ref.uri, playlist=True)\n"
    )
    assert s.count(old_refresh) == 1, f"old_refresh count={s.count(old_refresh)}"
    new_refresh = (
        "        playlist_refs = [\n"
        "            ref for ref in self.core.playlists.as_list().get() if ref.name\n"
        "        ]\n"
        "        current_uris = {ref.uri for ref in playlist_refs}\n"
        "\n"
        "        with self._lock:\n"
        "            stale_uris = set(self._playlist_name_from_uri) - current_uris\n"
        "            for uri in stale_uris:\n"
        "                stale_name = self._playlist_name_from_uri.pop(uri)\n"
        "                if self._uri_from_name.get(stale_name) == uri:\n"
        "                    del self._uri_from_name[stale_name]\n"
        "\n"
        "            for playlist_ref in playlist_refs:\n"
        "                name = self._invalid_playlist_chars.sub(\"|\", playlist_ref.name)\n"
        "                self.insert(name, playlist_ref.uri, playlist=True)\n"
    )
    s = s.replace(old_refresh, new_refresh, 1)

    open(p, "w").write(s)
    print(
        "patched uri_mapper.py: MpdUriMapperが全クライアント接続間で共有され"
        "ロック無しでdictを読み書きしているため、複数接続が同時にbrowse/"
        "プレイリスト一覧操作を行うと走査中dict変更でRuntimeErrorが発生し"
        "無関係な接続まで問答無用で切断されてしまう不具合を修正 "
        "(threading.RLockでdict操作を直列化、core呼び出し自体はロック外に維持)"
    )
