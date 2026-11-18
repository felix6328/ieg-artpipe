import re,sys,subprocess
rev=sys.argv[1]
A='binaries/data/mods/public/art/actors/units/'
names=subprocess.run(['git','ls-tree','-r','--name-only',rev,'--',A],capture_output=True,text=True).stdout.split()
cand=[n for n in names if re.search(r'_e_[a-z]+\.xml$',n)]
out=[]
for n in cand:
    s=subprocess.run(['git','show',f'{rev}:{n}'],capture_output=True,text=True).stdout
    for m in re.findall(r'<prop[^>]*actor="(units/[^"]+)"',s):
        if re.search(r'_(a|b)_[a-z]+\.xml$',m): out.append((n.split('units/')[1],m))
print(rev,len(cand),'expert actors;',len(out),'rank mismatches'); [print(' ',x) for x in out]
