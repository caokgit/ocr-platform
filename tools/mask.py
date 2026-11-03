#!/usr/bin/env python3
"""Mask network addresses and private names in text read on stdin (AGENTS.md "Safety and approvals").

    some-command 2>&1 | python3 tools/mask.py

- IPv4: private ranges (10/8, 172.16/12, 192.168/16), 0.0.0.0 and 127.x stay in full (internal addresses
  are shown, owner 2026-10-30); every other, public address becomes <ip>
- IPv6: global addresses (2000::/3) become <v6>
- names: each line of the gitignored .scratch_box/mask-words (such as the box's hostname, which is also
  its Kubernetes node name) becomes <box>
"""

import re
import sys
from pathlib import Path

IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
IPV6 = re.compile(r"\b[23][0-9a-f]{3}:[0-9a-f:]+", re.IGNORECASE)
WORDS_FILE = Path(__file__).resolve().parent.parent / ".scratch_box" / "mask-words"


def mask_ipv4(match: re.Match) -> str:
    address = match.group(0)
    a, b = address.split(".")[:2]
    internal = (address == "0.0.0.0" or a in ("10", "127") or (a == "172" and 16 <= int(b) <= 31)
                or (a == "192" and b == "168"))
    return address if internal else "<ip>"


def load_words() -> list[str]:
    if not WORDS_FILE.exists():
        return []
    return [w.strip() for w in WORDS_FILE.read_text().splitlines() if w.strip()]


def mask(line: str, words: list[str]) -> str:
    line = IPV6.sub("<v6>", IPV4.sub(mask_ipv4, line))
    for word in words:
        line = re.sub(re.escape(word), "<box>", line, flags=re.IGNORECASE)
    return line


if __name__ == "__main__":
    words = load_words()
    for line in sys.stdin:
        sys.stdout.write(mask(line, words))
