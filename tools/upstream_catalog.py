"""上游原文目录 —— 让 vendored 的第三方 skill 原文**找得到**，而不是躺在 2604 个文件里没人知道。

Not to be confused with `tools/capability_catalog.py`, which is this machine's OWN capability map
(modes + recipes + roster). This module catalogues the **read-only third-party text** under
`vendor/upstream-research-skills/`. Three things it is deliberately NOT:

* **Not capability.** The machine's capabilities are `orchestrator/mode_registry.yaml` + `agents/`
  (see `capability_catalog.py`). Nothing here runs: the vendoring allowlist admits markdown and license
  notices only, so the tree holds no script, hook, plugin manifest or MCP config at all.
* **Not an installer.** Listing a bundle never mounts, fetches, or executes it. The director's
  2026-08-04 decision was 「只挂原文，不跑任何东西」 and this verb does not reopen it.
* **Not in the director's search.** The workbench indexer sweeps `projects/<slug>/` only, so third-party
  text can never inflate artifact counts or surface as if it were our own work.

What it IS: a read-only catalogue so an agent (or the director) can find and READ what an upstream skill
actually says, instead of trusting our clean-room summary of it. Bundles are derived from where the real
`SKILL.md` files sit on disk — never a written-down list, which would rot on the next re-fetch.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MACHINE_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = MACHINE_ROOT / "vendor" / "upstream-research-skills"
MANIFEST = VENDOR_ROOT / "MANIFEST.json"

NOT_CAPABILITY = ("这些是**只读原文**，不是这台机器的能力。机器真正能跑的是 "
                  "`orchestrator/mode_registry.yaml` + `agents/`；这里一个文件都跑不起来"
                  "（只收了 markdown 和许可证，没有脚本 / hook / 插件清单 / MCP 配置）。")


def _manifest() -> dict[str, Any]:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def catalog() -> dict[str, Any]:
    """Sources + their skill bundles, derived from the real `SKILL.md` locations in the vendored tree."""
    data = _manifest()
    sources = []
    for source in data.get("sources") or []:
        snapshot = str(source.get("snapshot_dir") or "")
        bundles = sorted(
            str(Path(str(entry.get("path") or "")).parent).replace("\\", "/")
            for entry in source.get("files") or []
            if Path(str(entry.get("path") or "")).name == "SKILL.md"
        )
        sources.append({
            "source_id": str(source.get("source_id") or "?"),
            "repository": str(source.get("repository") or ""),
            "commit": str(source.get("commit") or "")[:12],
            "snapshot_dir": snapshot,
            "license": str(source.get("license_status") or "?"),
            "attribution_required": bool(source.get("attribution_required")),
            "declared_skills": source.get("declared_skill_count"),
            "bundles_found": len(bundles),
            "files": source.get("file_count"),
            "bundles": bundles,
            "root": str(VENDOR_ROOT / snapshot) if snapshot else "",
        })
    return {
        "present": MANIFEST.is_file(),
        "vendor_root": str(VENDOR_ROOT),
        "totals": data.get("totals") or {},
        "excluded_source_ids": (data.get("policy") or {}).get("excluded_source_ids") or [],
        "sources": sources,
        "not_capability": NOT_CAPABILITY,
    }


def find(query: str, *, limit: int = 25) -> dict[str, Any]:
    """Substring match over `<source_id>/<bundle path>`; every hit resolves to a real on-disk file."""
    needle = (query or "").strip().lower()
    hits: list[dict[str, Any]] = []
    data = catalog()
    for source in data["sources"]:
        for bundle in source["bundles"]:
            handle = f"{source['source_id']}/{bundle}"
            if needle and needle not in handle.lower():
                continue
            skill = Path(source["root"]) / bundle / "SKILL.md" if source["root"] else None
            hits.append({
                "handle": handle,
                "source_id": source["source_id"],
                "bundle": bundle,
                "skill_md": str(skill) if skill else "",
                "on_disk": bool(skill and skill.is_file()),
                "license": source["license"],
            })
    return {"query": query, "matched": len(hits), "hits": hits[:limit],
            "truncated": max(0, len(hits) - limit), "not_capability": NOT_CAPABILITY}


def render_catalog(data: dict[str, Any]) -> str:
    if not data["present"]:
        return ("# 上游原文目录\n\n> 没找到 vendored 的上游原文（`vendor/upstream-research-skills/`）。\n"
                "> 查一下：`python -m research_agent_teams.tools.vendor_upstream_skills verify`\n")
    totals = data["totals"]
    lines = ["# 上游原文目录（只读，不可执行）", "",
             f"> {totals.get('sources', 0)} 个来源 · {totals.get('skill_bundles', 0)} 份 skill 原文 · "
             f"{totals.get('files', 0)} 个文件。", "",
             f"> ⚠️ {data['not_capability']}", "",
             "| 来源 | 许可 | 上游声明 | 实际找到 | 文件 | commit |",
             "|---|---|---:|---:|---:|---|"]
    for source in data["sources"]:
        lines.append(f"| `{source['source_id']}` | {source['license']} | "
                     f"{source['declared_skills'] or '—'} | {source['bundles_found']} | "
                     f"{source['files']} | `{source['commit']}` |")
    lines += ["", "按名字找一份原文，然后直接读它：", "", "```bash",
              "python -m research_agent_teams.workbench capabilities deep-research",
              "```", ""]
    if data["excluded_source_ids"]:
        lines += ["> 故意排除的来源（安全原因，不是偏好）："
                  + "、".join(f"`{x}`" for x in data["excluded_source_ids"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def render_hits(result: dict[str, Any]) -> str:
    lines = [f"「{result['query'] or '全部'}」命中 {result['matched']} 份 skill 原文", ""]
    for hit in result["hits"]:
        mark = "" if hit["on_disk"] else "　⚠️ 清单里有、磁盘上没有（跑一次 vendor verify）"
        lines += [f"- `{hit['handle']}`　[{hit['license']}]{mark}", f"    {hit['skill_md']}"]
    if result["truncated"]:
        lines.append(f"- …… 另外 {result['truncated']} 份（收窄关键词，或加 `--json`）")
    lines += ["", f"> {result['not_capability']}"]
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["catalog", "find", "render_catalog", "render_hits", "NOT_CAPABILITY", "VENDOR_ROOT"]
