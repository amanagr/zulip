import os, re

def ctorem(matchobj):
    a = matchobj.group(1).strip()
    a = int(float(a)) if int(float(a)) == float(a) else float(a)
    return str(a/16)

def repl(matchobj):
    # return 'font-size: '  + re.sub('(.+)', ctorem, str(matchobj.group(1))) + 'rem;'
    return 'font-size: $medium_font_size'

for dname, dirs, files in os.walk("."):
    for fname in files:
        if fname[-3:] == 'css':
            fpath = os.path.join(dname, fname)
            print(fpath)
            with open(fpath, 'r') as f:
                s = f.read()
                # x = re.sub(r'font-size: (\d+\.?\d*)px;', repl, s)
                x = re.sub(r'font-size: 100%', repl, s)
                print(x.strip(), file=open(fpath, 'w'))
