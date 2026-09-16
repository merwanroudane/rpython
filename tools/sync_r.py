"""Copy r-package/R/*.R into src/rpython/r/ (bundled with the wheel). Run after editing R sources."""
import filecmp, os, shutil, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC, DST = os.path.join(ROOT, "r-package", "R"), os.path.join(ROOT, "src", "rpython", "r")
os.makedirs(DST, exist_ok=True)
changed = []
for f in sorted(os.listdir(SRC)):
    if f.endswith(".R"):
        s, d = os.path.join(SRC, f), os.path.join(DST, f)
        if not os.path.exists(d) or not filecmp.cmp(s, d, shallow=False):
            shutil.copyfile(s, d); changed.append(f)
for f in os.listdir(DST):
    if f.endswith(".R") and not os.path.exists(os.path.join(SRC, f)):
        os.remove(os.path.join(DST, f)); changed.append("-" + f)
if "--check" in sys.argv and changed:
    print("out of sync:", changed); sys.exit(1)
print("synced:", changed or "nothing")
