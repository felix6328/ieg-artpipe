"""R5 evidence: check that every mesh/texture/prop/variant referenced by actor & variant XMLs exists.
Run inside a blobless clone with sparse checkout of art/actors, art/variants, art/materials,
after writing the full art file list:  git ls-tree -r --name-only HEAD -- binaries/data/mods/public/art > /tmp/art_files.txt
Verified 2026-11-16 at HEAD 14b258b10: mesh 7362, texture 22747, prop 21447, variant 17567 refs; 0 missing.
"""
import re, glob, collections, json
A = 'binaries/data/mods/public/art/'
files = set(l.strip() for l in open('/tmp/art_files.txt'))
miss = collections.defaultdict(list); n = collections.Counter()
rules = [('mesh', r'<mesh>\s*([^<\s]+)\s*</mesh>', 'meshes/'),
         ('texture', r'<texture[^>]*file="([^"]+)"', 'textures/skins/'),
         ('prop', r'<prop[^>]*actor="([^"]+)"', 'actors/'),
         ('variant', r'<variant[^>]*file="([^"]+)"', 'variants/')]
for f in glob.glob(A+'actors/**/*.xml', recursive=True) + glob.glob(A+'variants/**/*.xml', recursive=True):
    s = open(f, errors='ignore').read()
    for kind, pat, prefix in rules:
        for m in re.findall(pat, s):
            if not m: continue
            n[kind] += 1
            if A + prefix + m not in files: miss[kind].append((f, m))
print(dict(n)); print({k: len(v) for k, v in miss.items()})
json.dump(miss, open('refcheck_out.json', 'w'), indent=1)
