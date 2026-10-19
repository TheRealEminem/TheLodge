"""Tags, normalized the same way in every module, so "Angel Investor" in one is "angel-investor" in all of them."""


def normalize_tags(tags: list[str]) -> list[str]:
    """Lowercase, hyphenated, de-duplicated: "Angel Investor" -> "angel-investor"."""
    seen: list[str] = []
    for t in tags:
        t = "-".join(t.strip().lower().split())[:64]
        if t and t not in seen:
            seen.append(t)
    return seen
