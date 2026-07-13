"""Guess likely email addresses from a person's name + company domain.

Only useful when we have a candidate name (e.g. a recruiter found by other
means). Each guess is piped through the pluggable verifier by the chain.
"""

from __future__ import annotations


def _clean(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalpha())


def guess_patterns(first: str, last: str, domain: str) -> list[str]:
    """Return common corporate email patterns, most-likely first."""
    f = _clean(first)
    l = _clean(last)
    domain = domain.lower().lstrip("www.").split("/")[0]
    if not f or not domain:
        return []
    fi = f[0]
    li = l[0] if l else ""

    patterns = []
    if l:
        patterns += [
            f"{f}.{l}@{domain}",   # first.last
            f"{f}{l}@{domain}",    # firstlast
            f"{fi}{l}@{domain}",   # flast
            f"{f}@{domain}",       # first
            f"{fi}.{l}@{domain}",  # f.last
            f"{f}_{l}@{domain}",   # first_last
            f"{l}{fi}@{domain}",   # lastf
        ]
    else:
        patterns += [f"{f}@{domain}"]

    # Dedupe preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
