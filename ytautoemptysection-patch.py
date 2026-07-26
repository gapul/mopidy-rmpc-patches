# mopidy_ytmusic.backend.py の _get_auto_playlists() ("Auto Playlists" ホーム相当、
# self.library.ytbrowse を更新し ytmusic:auto / ytmusic:auto:<hash> の browse で使われる)
# にある「空セクションを削除する」ループがオフバイワンで、先頭セクション(index 0)を
# 決して削除しない不具合。
#
#     # Delete empty sections
#     for i in range(len(browse) - 1, 0, -1):
#         if len(browse[i]["items"]) == 0:
#             browse.pop(i)
#
# range(len(browse) - 1, 0, -1) は stop=0 が exclusive のため i=0 に到達せず、
# browse[0] がどれだけ空でも pop されない。ytautoplaylistfix-patch.py 適用後の
# parse_auto_playlists() は、タイトル欠落セクションは弾く(browseへ追加しない)ものの、
# 「セクション自体は追加されたが中の全アイテムが個別ガードでスキップされ items=[] のまま
# 残る」ケース (例: カルーセルの全曲がポッドキャスト/未対応type、あるいは全アイテムが
# musicTwoRowItemRenderer 以外の未知レンダラーで brId/ititle を解決できない) は正常系として
# 想定しており、その除去をこの「空セクション削除」ループに委ねている。そのケースが
# たまたま最初のセクションで発生すると、rmpc 側で ytmusic:auto を開いたときに中身の無い
# フォルダが残り続ける (エラーにはならないが、開いても何も表示されない空フォルダが
# 一覧に残る)。
#
# 対策: stop を -1 にして i=0 まで含める (他のインデックスは pop 後も再訪しないため
# 逆順ループの安全性に変化はない)。
p = "mopidy_ytmusic/backend.py"
s = open(p).read()

OLD = (
    '            for i in range(len(browse) - 1, 0, -1):\n'
    '                if len(browse[i]["items"]) == 0:\n'
    '                    browse.pop(i)\n'
)
NEW = (
    '            for i in range(len(browse) - 1, -1, -1):\n'
    '                if len(browse[i]["items"]) == 0:\n'
    '                    browse.pop(i)\n'
)

if NEW in s:
    print("backend.py already patched (ytautoemptysection), skip")
else:
    assert s.count(OLD) == 1, f"empty-section loop anchor count={s.count(OLD)}"
    s = s.replace(OLD, NEW, 1)
    open(p, "w").write(s)
    print(
        "patched backend.py: _get_auto_playlists()の空セクション削除ループが"
        "range(len(browse)-1, 0, -1)というオフバイワンで先頭セクション(index 0)を"
        "決して削除しない不具合を修正 (stop=-1にしてi=0まで含める)"
    )
