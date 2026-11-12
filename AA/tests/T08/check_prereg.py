"""Freeze and verify the T08 pre-registration.

    python check_prereg.py --freeze   # once, before any engine run: writes the sha256 into T08.md's header
    python check_prereg.py            # any time: recomputes it and exits non-zero if §1-§3 changed

Hashed: the text from the line '## 1. Idea and references' up to (not including) the line '## 4. Results',
UTF-8, LF line endings, trailing whitespace on each line stripped. The header is outside it.
"""
import hashlib
import re
import sys
from pathlib import Path

F = Path(__file__).with_name("T08.md")
HEAD = re.compile(r"^\*\*§1–§3 sha256:\*\* `([^`]*)`.*$", re.M)


def region(text: str) -> str:
    a = text.index("\n## 1. Idea and references") + 1
    b = text.index("\n## 4. Results") + 1
    return "\n".join(l.rstrip() for l in text[a:b].replace("\r\n", "\n").split("\n"))


def main() -> int:
    t = F.read_text(encoding="utf-8")
    h = hashlib.sha256(region(t).encode("utf-8")).hexdigest()
    m = HEAD.search(t)
    if m is None:
        print("no sha256 header line"); return 2
    cur = m.group(1)
    if "--freeze" in sys.argv:
        if cur != "PENDING":
            print(f"already frozen: {cur}"); return 1
        line = ("**§1–§3 sha256:** `%s` (the hash of the text from the line `## 1. Idea and references` to the line before "
                "`## 4. Results`, recomputed by `check_prereg.py`)" % h)
        F.write_text(t[:m.start()] + line + t[m.end():], encoding="utf-8")
        print("frozen", h); return 0
    if cur == "PENDING":
        print("not frozen yet; current hash", h); return 3
    ok = cur == h
    print("OK  " if ok else "CHANGED", h, "recorded", cur)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
