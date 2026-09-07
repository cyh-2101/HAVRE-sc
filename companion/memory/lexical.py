"""Language-neutral lexical evidence, including Chinese word fragments."""

import re

VERSION = "unicode-word-cjk-bigram-v1"


def tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.casefold()))
    for span in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(span[i:i + 2] for i in range(len(span) - 1))
    return words


def overlap(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    return len(a & b) / max(1, min(len(a), len(b)))
