#!/usr/bin/env python3
"""Check the repo's Markdown (AGENTS.md "Writing" and "Safety and approvals").

    python3 tools/check-docs.py        # exit 1 if anything is wrong

- every relative link and #anchor resolves (GitHub anchor rules; headings in code blocks ignored)
- no em dash
- no secret-shaped strings: JWTs, GitHub tokens, private keys
- internal (private) IPv4 addresses are allowed in the lab's private repo (AGENTS.md "Writing"); the public
  export masks them
- every page under docs/ is linked from its index: docs/README.md, or the README of a folder that keeps
  its own index (learn/, runbooks/, journal/; notes/ exists only in the export, where public/docs becomes docs/,
  so the public pages are index-checked by the export's own run)
- journal entries are named YYYY-MM-DD-<slug>.md
- a link in public/ resolves as in the public export, where public/ lies over the repo's root
  (docs/public-export.md#the-export-script)

Skips gitignored folders (.scratch*, .toolchain, .venv).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PREFIXES = (".scratch", ".toolchain", ".venv", ".git", "node_modules")
EM_DASH = "—"
SECRETS = {
    "JWT-shaped string": re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
    "GitHub token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def slug(heading):
    return re.sub(r"[^\w\- ]", "", heading.strip().lower().replace("`", "")).replace(" ", "-")


def strip_code(text):
    return re.sub(r"```.*?```", "", text, flags=re.S)


def skipped(path):
    return any(part.startswith(SKIP_PREFIXES) for part in path.relative_to(ROOT).parts)


def linked_targets(index):
    """Resolved .md targets an index page links to (a link to a folder counts as its README)."""
    out = set()
    for link in re.findall(r"\]\(([^)\s#]+)", strip_code(index.read_text())):
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        target = (index.parent / link).resolve()
        out.add(target / "README.md" if target.is_dir() else target)
    return out


PUBLIC = ROOT / "public"


def resolve(page, path):
    """A link's target; from a public/ page, the export's view: public/ first, else the same path in the repo."""
    target = (page.parent / path).resolve()
    if PUBLIC in page.parents and not target.exists() and PUBLIC in target.parents:
        return ROOT / target.relative_to(PUBLIC)
    return target


SELF_INDEXED = ("learn", "runbooks", "journal", "notes")
JOURNAL_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$")


def index_gaps(files):
    """docs/README.md lists every docs/ page, except folders that keep their own README index."""
    docs = ROOT / "docs"
    indexes = [docs / "README.md"] + [docs / d / "README.md" for d in SELF_INDEXED]
    linked = {i: linked_targets(i) if i.exists() else set() for i in indexes}
    gaps = []
    for p in files:
        if docs not in p.parents or p in linked:
            continue
        index = next((docs / d / "README.md" for d in SELF_INDEXED if docs / d in p.parents), docs / "README.md")
        if p.resolve() not in linked[index]:
            gaps.append(f"{p.relative_to(ROOT)}: not listed in {index.relative_to(ROOT)}")
        if p.parent == docs / "journal" and not JOURNAL_NAME.match(p.name):
            gaps.append(f"{p.relative_to(ROOT)}: journal entries are named YYYY-MM-DD-<slug>.md")
    return gaps


def main():
    files = [p for p in ROOT.rglob("*.md") if not skipped(p)]
    anchors = {p: {slug(h) for h in re.findall(r"^#+\s+(.*)$", strip_code(p.read_text()), re.M)}
               for p in files}
    problems = []
    for p in files:
        text = p.read_text()
        rel = p.relative_to(ROOT)
        for n, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                problems.append(f"{rel}:{n}: em dash")
            for name, pattern in SECRETS.items():
                if pattern.search(line):
                    problems.append(f"{rel}:{n}: {name}")
        for link in re.findall(r"\]\(([^)\s]+)\)", strip_code(text)):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, frag = link.partition("#")
            target = resolve(p, path) if path else p
            if not target.exists():
                problems.append(f"{rel}: missing target {link}")
            elif frag and target.is_file() and target.suffix == ".md" and frag not in anchors.get(target, set()):
                problems.append(f"{rel}: missing anchor {link}")
    problems += index_gaps(files)
    for line in problems:
        print(line)
    print(f"{len(files)} files checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
