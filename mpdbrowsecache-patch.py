# mopidy_mpd/uri_mapper.py の MpdUriMapper は、プレイリスト名前空間については
# mpdplaylistcache-patch.py で「削除/リネームされた旧エントリを purge する」修正が
# 既に入っているが、browse (ディレクトリ閲覧) 名前空間 (_browse_name_from_uri /
# _uri_from_name への insert(..., playlist=False) 経由の書き込み) には対応する
# purge が一切無い。TODO 全項目消化済みのため自走エージェントが mopidy_mpd の
# コード品質を再調査して発見した項目。
#
# 原因: dispatcher.py の MpdContext.browse() は、あるディレクトリ(base_path)を
# 列挙するたびに、そのディレクトリの子要素を無条件に _uri_map.insert() し続けるが、
# 以前そのディレクトリに存在した(が今回のリストには無い)子要素のキャッシュエントリを
# 一切削除しない。mopidy_ytmusic の "ytmusic:home" のように内容が日替わりで変わる
# (=同じ表示名の項目が別の browseId/URI で再出現しうる) バックエンドをブラウズし
# 続けると、_uri_from_name / _browse_name_from_uri は際限なく肥大化し続ける。
#
# さらに実害として、_create_unique_name() は「名前が既存だが URI が違う」場合に
# 無条件で衝突とみなし "Name [2]" のようなサフィックスを付ける。ある子要素が古い
# URI(U1)で一度キャッシュされたまま、後日同じ表示名だが別 URI(U2)の項目が
# 同じディレクトリに現れると、U1 のエントリが既に無効(そのディレクトリから消えている)
# にもかかわらず purge されないため、U2 側が誤って "Name [2]" という不要な
# サフィックス付き名前になってしまう。これは mpdplaylistcache-patch.py が
# プレイリスト側で修正したのと全く同じ設計ミスが、browse 側にも存在する形。
#
# 修正方針: refresh_playlists_mapping() と同じ流儀で、あるディレクトリを
# ブラウズする際に、まず現在の子要素の URI 集合を確定させ、そのディレクトリの
# 直接の子として過去にキャッシュされたが今回のリストに無いエントリ(stale)を
# purge してから insert() する。

p = "mopidy_mpd/uri_mapper.py"
s = open(p).read()

MARKER = "def refresh_browse_children(self, base_path, current_uris):"
if MARKER in s:
    print("mpdbrowsecache already applied to uri_mapper.py, skip")
else:
    old_block = (
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
        "\n"
        "    def uri_from_name(self, name):\n"
    )
    assert s.count(old_block) == 1, f"old_block count={s.count(old_block)}"

    new_block = (
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
        "\n"
        "    def refresh_browse_children(self, base_path, current_uris):\n"
        '        """\n'
        "        Purge cache entries for direct children of base_path that are no\n"
        "        longer present in current_uris (the freshly listed children), so\n"
        "        a name reused for a different URI in a dynamic directory (e.g. a\n"
        "        YouTube Music home/browse listing that changes over time) does not\n"
        "        keep resolving to a dead URI and does not get needlessly\n"
        "        uniquified against a stale entry.\n"
        '        """\n'
        '        prefix = base_path + "/"\n'
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
        "\n"
        "    def uri_from_name(self, name):\n"
    )
    assert new_block != old_block
    s = s.replace(old_block, new_block, 1)

    open(p, "w").write(s)
    print(
        "patched uri_mapper.py: refresh_browse_children()を追加 "
        "(browse名前空間のstale子エントリをpurgeするヘルパ)"
    )

p2 = "mopidy_mpd/dispatcher.py"
s2 = open(p2).read()

MARKER2 = "self._uri_map.refresh_browse_children(\n"
if MARKER2 in s2:
    print("mpdbrowsecache already applied to dispatcher.py, skip")
else:
    old_block2 = (
        "        path_and_futures = [(root_path, self.core.library.browse(uri))]\n"
        "        while path_and_futures:\n"
        "            base_path, future = path_and_futures.pop()\n"
        "            for ref in future.get():\n"
        "                if ref.name is None or ref.uri is None:\n"
        "                    continue\n"
        "\n"
        '                path = "/".join([base_path, ref.name.replace("/", "")])\n'
        "                path = self._uri_map.insert(path, ref.uri)\n"
        "\n"
        "                if ref.type == ref.TRACK:\n"
        "                    if lookup:\n"
        "                        # TODO: can we lookup all the refs at once now?\n"
        "                        yield (path, self.core.library.lookup(uris=[ref.uri]))\n"
        "                    else:\n"
        "                        yield (path, ref)\n"
        "                else:\n"
        "                    yield (path, None)\n"
        "                    if recursive:\n"
        "                        path_and_futures.append(\n"
        "                            (path, self.core.library.browse(ref.uri))\n"
        "                        )\n"
    )
    assert s2.count(old_block2) == 1, f"old_block2 count={s2.count(old_block2)}"

    new_block2 = (
        "        path_and_futures = [(root_path, self.core.library.browse(uri))]\n"
        "        while path_and_futures:\n"
        "            base_path, future = path_and_futures.pop()\n"
        "            refs = [\n"
        "                ref\n"
        "                for ref in future.get()\n"
        "                if ref.name is not None and ref.uri is not None\n"
        "            ]\n"
        "            self._uri_map.refresh_browse_children(\n"
        "                base_path, {ref.uri for ref in refs}\n"
        "            )\n"
        "            for ref in refs:\n"
        '                path = "/".join([base_path, ref.name.replace("/", "")])\n'
        "                path = self._uri_map.insert(path, ref.uri)\n"
        "\n"
        "                if ref.type == ref.TRACK:\n"
        "                    if lookup:\n"
        "                        # TODO: can we lookup all the refs at once now?\n"
        "                        yield (path, self.core.library.lookup(uris=[ref.uri]))\n"
        "                    else:\n"
        "                        yield (path, ref)\n"
        "                else:\n"
        "                    yield (path, None)\n"
        "                    if recursive:\n"
        "                        path_and_futures.append(\n"
        "                            (path, self.core.library.browse(ref.uri))\n"
        "                        )\n"
    )
    assert new_block2 != old_block2
    s2 = s2.replace(old_block2, new_block2, 1)

    open(p2, "w").write(s2)
    print(
        "patched dispatcher.py: browse()がディレクトリ列挙のたびに"
        "stale子エントリをrefresh_browse_children()でpurgeするよう修正 "
        "(名前が別URIで再利用された際に不要な[2]サフィックスが付く不具合を解消)"
    )
