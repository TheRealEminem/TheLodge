"""One search box for every module: each module searches its own things, the host merges the answers."""
import logging

from . import module

log = logging.getLogger("core.search")


def search(q: str, limit: int = 8) -> list[dict]:
    """[{module, module_name, hits: [{id, ref, title, snippet, href}]}], modules with no hits left out."""
    q = q.strip()
    if not q:
        return []
    groups = []
    for m in module.all_modules():
        if not m.search:
            continue
        try:
            hits = m.search(q, limit)
        except Exception:  # noqa: BLE001 - one module's broken search shouldn't hide the others
            log.exception("Search failed in %s", m.id)
            continue
        out = []
        for hit in hits:
            described = module.describe(f"{m.id}:{hit['id']}") or {}
            out.append({"ref": f"{m.id}:{hit['id']}", "href": described.get("href", f"#/{m.id}/{hit['id']}"), **hit})
        if out:
            groups.append({"module": m.id, "module_name": m.name, "hits": out})
    return groups
