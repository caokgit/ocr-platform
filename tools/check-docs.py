#!/usr/bin/env python3
"""Check the repo's Markdown (AGENTS.md "Writing" and "Safety and approvals"); shared by the owner's repos.

    python3 tools/check-docs.py        # exit 1 if anything is wrong

Always:
- every relative link and #anchor resolves (GitHub anchor rules; headings in code blocks ignored)
- no em dash
- no secret-shaped strings: JWTs, GitHub tokens, private keys, Azure keys and SAS signatures, Azure resource id paths
- every page under docs/ is linked from its index: docs/README.md, or the README of a folder that keeps its own index
- journal entries are named YYYY-MM-DD-<slug>.md
- in a sibling repo (method/VERSION exists), warnings only: a method file edited here and not pushed to the source, or
  a source checkout holding a newer method (docs/specs/method.md in ml-init); a session ends with neither

Per repo, from tools/repo.toml:
- [docs] self_indexed: the docs/ folders that keep their own README index
- [docs] public_overlay: a folder laid over the repo's root in a public export; its links resolve as in the export
- [check] ipv4 = "forbid": no IPv4 address other than 127.0.0.1 and 0.0.0.0 ("allow" by default)
- [check] guid = "forbid": no GUID, such as a subscription, tenant or workspace id ("allow" by default)

Skips gitignored folders (.scratch*, .toolchain, .terraform, .venv).
"""

import hashlib
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "tools" / "repo.toml"
CONFIG = tomllib.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
DOCS_CONFIG = CONFIG.get("docs", {})
CHECKS = CONFIG.get("check", {})

SKIP_PREFIXES = (".scratch", ".toolchain", ".terraform", ".venv", ".git", ".claude", "node_modules")
EM_DASH = "—"
SECRETS = {
    "JWT-shaped string": re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
    "GitHub token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Azure key or SAS signature": re.compile(r"(AccountKey|SharedAccessKey|sig)=[A-Za-z0-9%+/]{16,}"),
    "Azure resource id path": re.compile(r"/subscriptions/[^/\s<>]+/resourceGroups/", re.I),
}
if CHECKS.get("guid") == "forbid":
    SECRETS["GUID (an Azure id?)"] = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
if CHECKS.get("ipv4") == "forbid":
    SECRETS["IPv4 address"] = re.compile(
        r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


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


PUBLIC = ROOT / DOCS_CONFIG["public_overlay"] if DOCS_CONFIG.get("public_overlay") else None


def resolve(page, path):
    """A link's target; from a public overlay page, the export's view: the overlay first, else the repo."""
    target = (page.parent / path).resolve()
    if PUBLIC and PUBLIC in page.parents and not target.exists() and PUBLIC in target.parents:
        return ROOT / target.relative_to(PUBLIC)
    return target


SELF_INDEXED = tuple(DOCS_CONFIG.get("self_indexed", ["learn", "runbooks", "journal"]))
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


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def method_drift():
    """In a sibling repo: method files edited here and not pushed, and a newer method in the source (both warnings)."""
    version = ROOT / "method" / "VERSION"
    if not version.exists():
        return [], []
    problems, warnings = [], []
    meta, synced = {}, []
    for line in version.read_text().splitlines():
        if re.match(r"^[0-9a-f]{64}  ", line):
            digest, path = line.split("  ", 1)
            synced.append((digest, path))
        elif " " in line:
            key, value = line.split(" ", 1)
            meta[key] = value
    edited = set()
    for digest, path in synced:
        f = ROOT / path
        if not f.exists() or sha256(f.read_bytes()) != digest:
            edited.add(path)
            warnings.append(f"{path}: edited here, not yet in the source; run tools/sync-method.sh push \"<what changed>\"")
    source = Path(os.path.expanduser(meta.get("source", "")))
    if meta.get("source") and (source / "method" / "MANIFEST").exists():
        manifest = [l.strip() for l in (source / "method" / "MANIFEST").read_text().splitlines()
                    if l.strip() and not l.lstrip().startswith("#")]
        ours = {path: digest for digest, path in synced}
        for path in manifest:
            shown = subprocess.run(["git", "-C", str(source), "show", f"HEAD:{path}"], capture_output=True)
            if shown.returncode != 0:
                continue
            if ours.get(path) != sha256(shown.stdout):
                if path in edited:
                    warnings.append(f"{path}: changed both here and in the source ({meta['source']}); merge it by hand")
                else:
                    warnings.append(f"{path}: the source ({meta['source']}) has a newer version; run tools/sync-method.sh")
    return problems, warnings


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
    drift, warnings = method_drift()
    problems += drift
    for line in problems:
        print(line)
    for line in warnings:
        print(f"warning: {line}")
    print(f"{len(files)} files checked, {len(problems)} problem(s)" + (f", {len(warnings)} warning(s)" if warnings else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
