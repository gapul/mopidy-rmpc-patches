# mopidy_mpd/protocol/connection.py の albumart/readpicture (mpd-patch.py が追加、
# mpdalbumartrace-patch.py がスレッド安全化) は成功時のみ `_MPDART_CACHE` に
# キャッシュし、失敗時 (get_images() が例外/空・ダウンロード失敗) は一切キャッシュ
# しない。TODO/既知の残課題を全項目消化済みのため自走エージェントがrmpc本体
# (mierak/rmpc) を実際に clone してソース確認したところ、rmpc-shared/src/mpd_client_ext.rs
# の `find_album_art()` (デフォルト order は AlbumArtOrder::EmbeddedFirst、
# rmpc/src/core/command.rs で現在曲のアートを取得する際に実際に使われる) は
# 「先に readpicture を試し、結果が None または ACK50(NoExist) なら自動的に
# albumart へフォールバックする」設計であることを確認した。
#
# 実害: mopidy_ytmusic backend の library.get_images() (library.py) は、
# アルバム情報が欠落/プライベート化/地域制限等で `self.backend.api.get_album()`
# (実際のYouTube Music APIへのネットワーク呼び出し) が失敗する曲に対しては
# 例外を握り潰し images=[] を返すだけで、成功結果と違って一切キャッシュしない。
# このため readpicture→albumart のフォールバック1往復だけで同一の失敗する
# YTMusic API呼び出しを2回連続で無駄打ちし、かつ `_MPDART_CACHE` に何も
# 残らないため、同じ曲が再度表示・再生・キュー投入されるたびに(プロセスが
# 生きている限り永久に)同じ失敗APIコールが繰り返される。rmpc の
# `AlbumArtOrder::EmbeddedOnly`/`FileOnly` (config/album_art.rs でユーザーが
# 選択可能) 設定時はフォールバックが無く1回で済むが、既定の `EmbeddedFirst`
# では常に2回発生する。
#
# 対策: 成功時の `_MPDART_CACHE` と対になる負のキャッシュ `_MPDART_NEG_CACHE`
# (uri の集合) を導入し、`_mpdart_bytes()` の3つの失敗経路 (get_images()
# 例外・imgs空・ダウンロード失敗) 全てで記録する。読み書きは既存の
# `_mpdart_lock` で直列化し (mpdalbumartrace-patch.pyと同じ流儀)、
# `_MPDART_CACHE` と同じ「64件超で全clear」というサイズ上限方式を踏襲する
# (TTLではなくキャッシュ上限超過を再試行のリセット点とすることで、
# 正キャッシュと対称な設計に保つ)。`_mpdart_send()` は既に `data` が
# falsy なら `MpdNoExistError` を送出する実装のため、応答内容・ACKコードは
# 一切変更なし (副作用は無駄なAPI呼び出し/ダウンロード試行の削減のみ)。

p = "mopidy_mpd/protocol/connection.py"
s = open(p).read()

MARKER = "_MPDART_NEG_CACHE"
if MARKER in s:
    print("mpdalbumartnegcache already applied to connection.py, skip")
else:
    old = (
        "_mpdart_logger = _mpdart_logging.getLogger('mopidy_mpd.albumart')\n"
        "_MPDART_CACHE = {}\n"
        "# 全クライアント接続(各々別スレッドのMpdSessionアクター)が上記のdictを共有\n"
        "# するため、読み書きはLockで直列化する(mpdalbumartrace-patch.py)。\n"
        "_mpdart_lock = _mpdart_threading.Lock()\n"
        "\n"
        "\n"
        '@protocol.commands.add("binarylimit", limit=protocol.UINT)\n'
        "def binarylimit(context, limit):\n"
        "    # 1チャンク上限を保持 (albumart のチャンク分割で使用)。\n"
        "    # 実MPD (ClientCommands.cxx handle_binary_limit()) と同じく64未満は拒否。\n"
        "    if limit < 64:\n"
        '        raise exceptions.MpdArgError("Value too small")\n'
        "    context.session.binary_limit = limit\n"
        "\n"
        "\n"
        "def _mpdart_bytes(context, uri):\n"
        "    with _mpdart_lock:\n"
        "        if uri in _MPDART_CACHE:\n"
        "            return _MPDART_CACHE[uri]\n"
        "    try:\n"
        "        images = context.core.library.get_images([uri]).get()\n"
        "    except Exception as e:\n"
        "        _mpdart_logger.warning('get_images failed for %s: %s', uri, e)\n"
        "        return None\n"
        "    imgs = images.get(uri) if images else None\n"
        "    if not imgs:\n"
        "        return None\n"
        "    best = max(imgs, key=lambda im: (getattr(im, 'width', 0) or 0) * (getattr(im, 'height', 0) or 0))\n"
        "    url = best.uri\n"
        "    if url.startswith('//'):\n"
        "        url = 'https:' + url\n"
        "    try:\n"
        "        req = _mpdart_urllib.Request(url, headers={'User-Agent': 'Mopidy-MPD'})\n"
        "        with _mpdart_urllib.urlopen(req, timeout=10) as resp:\n"
        "            data = resp.read()\n"
        "    except Exception as e:\n"
        "        _mpdart_logger.warning('art download failed for %s: %s', url, e)\n"
        "        return None\n"
        "    with _mpdart_lock:\n"
        "        if len(_MPDART_CACHE) > 64:\n"
        "            _MPDART_CACHE.clear()\n"
        "        _MPDART_CACHE[uri] = data\n"
        "    return data\n"
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "_mpdart_logger = _mpdart_logging.getLogger('mopidy_mpd.albumart')\n"
        "_MPDART_CACHE = {}\n"
        "# get_images()/ダウンロードが失敗したuriを記録する負のキャッシュ\n"
        "# (mpdalbumartnegcache-patch.py)。readpicture->albumartフォールバック\n"
        "# (rmpc既定のAlbumArtOrder::EmbeddedFirst)や再表示のたびに同一の\n"
        "# 失敗するYTMusic API呼び出しを繰り返さないための対策。\n"
        "_MPDART_NEG_CACHE = set()\n"
        "# 全クライアント接続(各々別スレッドのMpdSessionアクター)が上記のdictを共有\n"
        "# するため、読み書きはLockで直列化する(mpdalbumartrace-patch.py)。\n"
        "_mpdart_lock = _mpdart_threading.Lock()\n"
        "\n"
        "\n"
        '@protocol.commands.add("binarylimit", limit=protocol.UINT)\n'
        "def binarylimit(context, limit):\n"
        "    # 1チャンク上限を保持 (albumart のチャンク分割で使用)。\n"
        "    # 実MPD (ClientCommands.cxx handle_binary_limit()) と同じく64未満は拒否。\n"
        "    if limit < 64:\n"
        '        raise exceptions.MpdArgError("Value too small")\n'
        "    context.session.binary_limit = limit\n"
        "\n"
        "\n"
        "def _mpdart_neg_cache_add(uri):\n"
        "    with _mpdart_lock:\n"
        "        if len(_MPDART_NEG_CACHE) > 64:\n"
        "            _MPDART_NEG_CACHE.clear()\n"
        "        _MPDART_NEG_CACHE.add(uri)\n"
        "\n"
        "\n"
        "def _mpdart_bytes(context, uri):\n"
        "    with _mpdart_lock:\n"
        "        if uri in _MPDART_CACHE:\n"
        "            return _MPDART_CACHE[uri]\n"
        "        if uri in _MPDART_NEG_CACHE:\n"
        "            return None\n"
        "    try:\n"
        "        images = context.core.library.get_images([uri]).get()\n"
        "    except Exception as e:\n"
        "        _mpdart_logger.warning('get_images failed for %s: %s', uri, e)\n"
        "        _mpdart_neg_cache_add(uri)\n"
        "        return None\n"
        "    imgs = images.get(uri) if images else None\n"
        "    if not imgs:\n"
        "        _mpdart_neg_cache_add(uri)\n"
        "        return None\n"
        "    best = max(imgs, key=lambda im: (getattr(im, 'width', 0) or 0) * (getattr(im, 'height', 0) or 0))\n"
        "    url = best.uri\n"
        "    if url.startswith('//'):\n"
        "        url = 'https:' + url\n"
        "    try:\n"
        "        req = _mpdart_urllib.Request(url, headers={'User-Agent': 'Mopidy-MPD'})\n"
        "        with _mpdart_urllib.urlopen(req, timeout=10) as resp:\n"
        "            data = resp.read()\n"
        "    except Exception as e:\n"
        "        _mpdart_logger.warning('art download failed for %s: %s', url, e)\n"
        "        _mpdart_neg_cache_add(uri)\n"
        "        return None\n"
        "    with _mpdart_lock:\n"
        "        if len(_MPDART_CACHE) > 64:\n"
        "            _MPDART_CACHE.clear()\n"
        "        _MPDART_CACHE[uri] = data\n"
        "        _MPDART_NEG_CACHE.discard(uri)\n"
        "    return data\n"
    )
    s = s.replace(old, new, 1)

    open(p, "w").write(s)
    print(
        "patched connection.py: albumart/readpictureが失敗したuriを一切"
        "キャッシュせず、rmpc既定のreadpicture->albumartフォールバックや"
        "再表示のたびに同一の失敗するYTMusic API呼び出し(get_album等)を"
        "無駄打ちし続ける不具合を修正 (_MPDART_NEG_CACHEで失敗uriを記録、"
        "_MPDART_CACHEと同じ64件超clearの流儀。応答内容/ACKコードは無変更)"
    )
