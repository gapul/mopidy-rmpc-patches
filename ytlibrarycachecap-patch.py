# mopidy_ytmusic.library.YTMusicLibraryProvider.__init__() が self.TRACKS/self.ALBUMS/
# self.ARTISTS/self.IMAGES を素の `{}` として初期化しており、getTrack()/playlistToTracks()/
# albumToTracks()/artistToTracks()/parseSearch()/get_images() など全ての書き込み箇所
# (grep で50箇所超) がキャッシュサイズの上限チェックや退避処理を一切持たない。
#
# 実害: mopidy はこの互換レイヤの想定運用(nix 経由の常駐サービスとして長時間稼働し
# rmpc から継続的に browse/search/lookup される)では再起動されず、ブラウズ・検索・
# 再生を重ねるたびに videoId/browseId をキーとする4つの辞書へ新規エントリが無条件に
# 追加され続け、プロセスの生涯にわたって単調増加する。ytlibrarylimit-patch.py が
# get_library_artists()/get_library_albums() 等の limit=100 上限を撤廃し全件取得
# (limit=None) するよう修正済みのため、大きなライブラリ・頻繁な検索ほど増加は
# 加速する。この「サイズ上限を持たないインプロセスキャッシュ」というバグの類型は
# 本コードベースでも既に2箇所で認識・対策済み: mopidy_mpd/protocol/connection.py の
# アルバムアート生バイト列キャッシュ `_MPDART_CACHE`/`_MPDART_NEG_CACHE` は64件超で
# 全消去、mpdaudioformatpreload-patch.py が追加した translator.py の
# `_audio_format_cache` は8件超で挿入順(古い順)に破棄する設計になっているが、
# はるかに書き込み頻度が高くエントリ点数も多いこの4つのライブラリキャッシュだけが
# 無制限のまま取り残されていた。TODO/既知の残課題を全項目消化済みのため自走エージェントが
# (Explore サブエージェントへの調査委任を経て) mopidy_mpd/mopidy_ytmusic を横断的に
# 再調査して新規発見した項目。
#
# 全書き込み箇所(50箇所超、今後追加されるパッチで増えうる)を個別に修正するのは
# 非現実的なため、mpdaudioformatpreload-patch.py と同じ FIFO(挿入順に破棄)方式を
# `dict` を継承した1クラスへカプセル化し、__init__ でのキャッシュ生成箇所だけを
# 差し替える。全ての書き込み箇所は既存通り `cache[key] = ...` のままで自動的に
# 上限管理下に入る (dict のインターフェースは変えないため他の挙動に影響しない)。
# 全ての読み出し箇所は `if key not in cache: cache[key] = ...` または直後の
# `cache[key]` 参照のみ (mopidy の各バックエンド呼び出しは pykka actor 経由で
# 単一スレッド逐次実行されるため、同一呼び出し内で "not in" 確認直後にエントリが
# 退避される競合は起こらない) であることを確認済みで、退避されたエントリへの
# 参照はキャッシュミスとして扱われ API から再取得されるだけで例外にはならない。
p = "mopidy_ytmusic/library.py"
s = open(p).read()

MARKER = "class _BoundedLibraryCache(dict):"
if MARKER in s:
    print("library.py already patched (ytlibrarycachecap), skip")
else:
    OLD = '''class YTMusicLibraryProvider(backend.LibraryProvider):
    root_directory = Ref.directory(uri="ytmusic:root", name="YouTube Music")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ytbrowse = []
        self.TRACKS = {}
        self.ALBUMS = {}
        self.ARTISTS = {}
        self.IMAGES = {}'''
    NEW = '''class _BoundedLibraryCache(dict):
    # videoId/browseId をキーとするライブラリキャッシュ用。無制限に増え続けないよう
    # 上限を超えたら挿入順(古い順)に破棄する (mpdaudioformatpreload-patch.py の
    # _audio_format_cache と同じ FIFO 方式)。dict のインターフェースはそのままなので
    # 既存の cache[key]=value / key in cache / cache[key] の呼び出し側は変更不要。
    def __init__(self, maxsize):
        super().__init__()
        self._maxsize = maxsize

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        while len(self) > self._maxsize:
            del self[next(iter(self))]


class YTMusicLibraryProvider(backend.LibraryProvider):
    root_directory = Ref.directory(uri="ytmusic:root", name="YouTube Music")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ytbrowse = []
        self.TRACKS = _BoundedLibraryCache(8192)
        self.ALBUMS = _BoundedLibraryCache(8192)
        self.ARTISTS = _BoundedLibraryCache(8192)
        self.IMAGES = _BoundedLibraryCache(8192)'''
    assert s.count(OLD) == 1, f"expected 1 occurrence of __init__ anchor (got {s.count(OLD)})"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched library.py: self.TRACKS/ALBUMS/ARTISTS/IMAGES が上限の無いdictのまま"
        "書き込まれ続け長時間稼働でメモリが単調増加する不具合を修正 "
        "(_BoundedLibraryCacheへ置換、各8192件超で挿入順に破棄するFIFOキャッシュ化)"
    )
