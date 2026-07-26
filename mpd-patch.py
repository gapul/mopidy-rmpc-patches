import re

# mopidy-mpd 3.3.0 に、新しめの MPD クライアント(rmpc 等)が使う以下を追加する:
#   - binarylimit : バイナリ応答の1チャンク上限。未実装だと接続時に弾かれるので受ける + 値を保持
#   - albumart / readpicture : アルバムアートのバイナリ取得。mopidy-mpd は未実装なので実装する。
#     アートURLは core.library.get_images (mopidy-ytmusic が album サムネを返す) から取得し、
#     画像を実ダウンロードして MPD のバイナリ応答形式 (size/binary ヘッダ + 生バイト + OK) で返す。
#     行ベースのディスパッチャにバイナリを割り込ませるため、ハンドラ内で
#     context.session.connection.queue_send に直接積み、末尾 OK だけ通常フローに任せる。
p = "mopidy_mpd/protocol/connection.py"
s = open(p).read()

MARKER = "rmpc album art support"
if MARKER not in s:
    s += (
        "\n\n"
        "# --- " + MARKER + " (patched) ---\n"
        "import logging as _mpdart_logging\n"
        "import urllib.request as _mpdart_urllib\n"
        "\n"
        "_mpdart_logger = _mpdart_logging.getLogger('mopidy_mpd.albumart')\n"
        "_MPDART_CACHE = {}\n"
        "\n"
        "\n"
        '@protocol.commands.add("binarylimit")\n'
        "def binarylimit(context, limit):\n"
        "    # 1チャンク上限を保持 (albumart のチャンク分割で使用)。未実装エラー回避も兼ねる。\n"
        "    try:\n"
        "        context.session.binary_limit = max(64, int(limit))\n"
        "    except (TypeError, ValueError):\n"
        "        pass\n"
        "\n"
        "\n"
        "def _mpdart_bytes(context, uri):\n"
        "    if uri in _MPDART_CACHE:\n"
        "        return _MPDART_CACHE[uri]\n"
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
        "    if len(_MPDART_CACHE) > 64:\n"
        "        _MPDART_CACHE.clear()\n"
        "    _MPDART_CACHE[uri] = data\n"
        "    return data\n"
        "\n"
        "\n"
        "def _mpdart_send(context, uri, offset, with_type):\n"
        "    data = _mpdart_bytes(context, uri)\n"
        "    if not data:\n"
        "        raise exceptions.MpdNoExistError('No file exists')\n"
        "    total = len(data)\n"
        "    limit = getattr(context.session, 'binary_limit', 8192) or 8192\n"
        "    # 全読了後 rmpc は offset==total で最終確認する。エラーにせず空バイナリを返す。\n"
        "    chunk = b'' if offset >= total else data[offset:offset + limit]\n"
        "    header = 'size: %d\\n' % total\n"
        "    if with_type:\n"
        "        mime = 'image/png' if data[:8] == b'\\x89PNG\\r\\n\\x1a\\n' else 'image/jpeg'\n"
        "        header += 'type: %s\\n' % mime\n"
        "    header += 'binary: %d\\n' % len(chunk)\n"
        "    context.session.connection.queue_send(header.encode('utf-8') + chunk + b'\\n')\n"
        "    return None\n"
        "\n"
        "\n"
        '@protocol.commands.add("albumart", offset=protocol.UINT)\n'
        "def albumart(context, uri, offset):\n"
        "    return _mpdart_send(context, uri, offset, with_type=False)\n"
        "\n"
        "\n"
        '@protocol.commands.add("readpicture", offset=protocol.UINT)\n'
        "def readpicture(context, uri, offset):\n"
        "    return _mpdart_send(context, uri, offset, with_type=True)\n"
    )
    open(p, "w").write(s)
    print("patched connection.py: binarylimit + albumart/readpicture を追加")
else:
    print(MARKER + " already present, skip")
