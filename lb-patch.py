p = "mopidy_listenbrainz/listenbrainz.py"
s = open(p).read()
# 1) 空でも送っていた release_name をリテラルから除去
s = s.replace('                "release_name": release,\n', '')
# 2) release が非空のときだけ付与する条件を挿入
anchor = "        if not now_playing:\n"
inject = ('        if release:\n'
          '            listen["track_metadata"]["release_name"] = release\n\n')
assert anchor in s, "anchor not found"
s = s.replace(anchor, inject + anchor, 1)
open(p, "w").write(s)
print("patched listenbrainz.py: empty release_name を送らないよう修正")
