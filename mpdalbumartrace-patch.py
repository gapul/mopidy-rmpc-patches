# mopidy_mpd/protocol/connection.py の albumart/readpicture (mpd-patch.py が追加) 用
# キャッシュ _MPDART_CACHE (uri -> ダウンロード済み画像バイト列) が、
# mpdurimaprace-patch.py/mpdchannelrace-patch.py/mpdpartitionrace-patch.py/
# mpdmountrace-patch.py/mpdqueuestorerace-patch.py/mpdupdatejobrace-patch.py が
# 修正した他の揮発性ストアと全く同じ理由 (全クライアント接続、各々別スレッドの
# MpdSessionアクターがロック無しで共有dictへ同時アクセス) でスレッド安全性を
# 欠いていた不具合。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# 横断調査 (rmpc本体ソースのalbumart/readpicture呼び出し経路を確認した上で、
# mpd-patch.py が実装したキャッシュ周りを再監査) して新規発見・追加した項目。
#
# 実害 (KeyError によるセッション切断): `_mpdart_bytes()` は
#   if uri in _MPDART_CACHE:
#       return _MPDART_CACHE[uri]
# という「存在確認」と「取得」が別々の2文(アトミックでない)になっており、この間に
# 別クライアントのリクエストがちょうど65件目のキャッシュを追加して
# `if len(_MPDART_CACHE) > 64: _MPDART_CACHE.clear()` を実行すると、前者の
# `uri in _MPDART_CACHE` が True と判定した直後に dict が丸ごと空になり、
# 後続の `_MPDART_CACHE[uri]` が KeyError を送出する。rmpc はブラウズ画面で
# アルバムアート格子を表示する際、多数の albumart/readpicture リクエストを
# 短時間に並行して送る (実際の使い方であり合成的なシナリオではない) ため、
# キャッシュが64件を超えた直後にヒットしたばかりのURIへアクセスが集中する状況は
# 現実的に起こりうる。`KeyError` は `exceptions.MpdAckError` のサブクラスでは
# ないため `dispatcher.py` の `_catch_mpd_ack_errors_filter` に捕捉されず、
# `session.py` にも保護が無いため pykka アクターの外まで伝播し、その
# albumart/readpicture を実行した接続がACKエラー無しに問答無用で切断される
# (mpdurimaprace-patch.py等の一連の修正と同型の実害)。
#
# 修正: モジュールレベルの `threading.Lock()` (`_mpdart_lock`) を導入し、
# `_mpdart_bytes()` 内の _MPDART_CACHE への読み書き (存在確認+取得、
# サイズ上限チェック+clear+新規登録) をそれぞれ `with _mpdart_lock:` で
# 直列化する。ネットワークダウンロード (urlopen、数百ms〜数秒かかりうる) は
# 意図的にロック区間の外に置く (他クライアントのキャッシュヒットをダウンロード
# 完了までブロックさせないため)。これにより同一URIへの初回リクエストが複数
# 並行した場合に多重ダウンロードが起こりうるが、それは既存の許容範囲内の
# 非効率 (クラッシュではない) であり、mpdqueuestorerace-patch.py等と同じ
# トレードオフの判断を踏襲する。

p = "mopidy_mpd/protocol/connection.py"
s = open(p).read()

MARKER = "_mpdart_lock"
if MARKER in s:
    print("mpdalbumartrace already applied to connection.py, skip")
else:
    old = (
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
    )
    assert s.count(old) == 1, f"old count={s.count(old)}"
    new = (
        "_mpdart_logger = _mpdart_logging.getLogger('mopidy_mpd.albumart')\n"
        "_MPDART_CACHE = {}\n"
        "# 全クライアント接続(各々別スレッドのMpdSessionアクター)が上記のdictを共有\n"
        "# するため、読み書きはLockで直列化する(mpdalbumartrace-patch.py)。\n"
        "_mpdart_lock = _mpdart_threading.Lock()\n"
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
    s = s.replace(old, new, 1)

    # import threading: connection.py は現状 threading を未importのため、既存の
    # import (logging/urllib) と同じ "as 別名" 流儀 (他パッチとの衝突回避) で追加する。
    import_anchor = "import urllib.request as _mpdart_urllib\n"
    assert s.count(import_anchor) == 1, f"import_anchor count={s.count(import_anchor)}"
    s = s.replace(
        import_anchor,
        import_anchor + "import threading as _mpdart_threading\n",
        1,
    )

    open(p, "w").write(s)
    print(
        "patched connection.py: albumart/readpicture用の画像キャッシュ"
        "(_MPDART_CACHE) が全クライアント接続間でロック無しに共有され、"
        "キャッシュ上限超過によるclear()と別接続の存在確認+取得の間のTOCTOUで"
        "KeyErrorが発生しセッションが問答無用で切断されてしまう不具合を修正 "
        "(threading.Lockでdict操作を直列化、ネットワークダウンロードはロック外、"
        "mpdurimaprace-patch.py等一連のrace修正と同じ流儀)"
    )
