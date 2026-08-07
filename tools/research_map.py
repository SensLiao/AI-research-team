"""研究链条图 —— 「哪个点子还没有对应的实验」。

The one view worth building of the four the external memo asked for. The other three (an Experiments
page, a Results & Figures page, a Writing page) are filters over a list that `workbench search` already
answers; a chain-coverage view answers something no existing verb does: **where the chain breaks**.

    论文 / 来源  ──→  点子  ──→  实验  ──→  结果  ──→  可引用
                       ↑ 断在这里 = 想过但没设计实验
                                ↑ 断在这里 = 设计了但没跑出结果
                                        ↑ 断在这里 = 有结果但不能写进论文

Read-only, index-free (it scans the vault directly, so it works before a `workbench reindex`), and it
states its own blind spot rather than implying coverage it cannot see: a link written as prose instead
of a `[[wikilink]]` is invisible to it, so a "断了" row means *no wikilink was found*, never *no such
work exists*. That distinction is the whole reason this is a navigation aid and not a verdict.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml

from .scope_guard import discover_vault_root

WIKILINK = re.compile(r"\[\[([a-z0-9][a-z0-9-]*)\]\]")

# The chain, in the order a research project actually walks it. Each step names the vault types that
# count as "downstream evidence that this step was taken".
CHAIN: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("idea", "点子", ("experiment", "protocol")),
    ("experiment", "实验", ("result",)),
    ("result", "结果", ()),
)
STEP_MEANING = {
    "idea": "想过，但没有任何实验页引用它 —— 还只是想法",
    "experiment": "设计了实验，但没有结果页引用它 —— 还没跑出东西",
    "result": "有结果，但不是 frozen —— 结构上还不能写进论文",
}


def _frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        data = yaml.safe_load("\n".join(lines[1:end]))
    except (StopIteration, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _projects_of(front: dict[str, Any]) -> set[str]:
    """A page's project binding. The vault serialises it three ways (string / list / absent), all real."""
    raw = front.get("project")
    if isinstance(raw, str) and raw.strip():
        return {raw.strip()}
    if isinstance(raw, list):
        return {str(x).strip() for x in raw if str(x).strip()}
    return set()


def scan_pages(vault_root: Optional[str | Path] = None) -> list[dict[str, Any]]:
    """Every vault page with the few fields the chain needs. Kinds are read off disk, never hardcoded."""
    root = Path(vault_root) if vault_root else discover_vault_root()
    if not root:
        return []
    wiki = Path(root) / "02-wiki"
    if not wiki.is_dir():
        return []
    pages: list[dict[str, Any]] = []
    for path in sorted(wiki.glob("*/*.md")):
        front = _frontmatter(path)
        try:
            body = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        pages.append({
            "slug": path.stem,
            "type": str(front.get("type") or path.parent.name.rstrip("s")),
            "title": str(front.get("title") or path.stem),
            "projects": _projects_of(front),
            "status": str(front.get("status") or ""),
            "result_status": str(front.get("result-status") or ""),
            "idea_status": str(front.get("idea-status") or ""),
            "links": set(WIKILINK.findall(body)),
            "path": str(path),
        })
    return pages


def build_map(project: Optional[str] = None, *,
              vault_root: Optional[str | Path] = None) -> dict[str, Any]:
    """Chain coverage: for each step, which pages have downstream evidence and which do not."""
    pages = scan_pages(vault_root)
    scoped = [p for p in pages if not project or project in p["projects"]]
    by_slug = {p["slug"]: p for p in pages}

    # Reverse index over ALL pages, not just the scoped ones: an in-project idea taken up by a page that
    # forgot its project binding is still taken up. Scoping the referrers too would invent broken links.
    referrers: dict[str, set[str]] = {}
    for page in pages:
        for target in page["links"]:
            if target in by_slug:
                referrers.setdefault(target, set()).add(page["slug"])

    counts: dict[str, int] = {}
    for page in scoped:
        counts[page["type"]] = counts.get(page["type"], 0) + 1

    steps: list[dict[str, Any]] = []
    for kind, label, downstream in CHAIN:
        rows = [p for p in scoped if p["type"] == kind]
        covered, broken = [], []
        for page in rows:
            if kind == "result":
                ok = page["result_status"] == "frozen"
            else:
                ok = any(by_slug[r]["type"] in downstream for r in referrers.get(page["slug"], set()))
            (covered if ok else broken).append(page)
        steps.append({
            "kind": kind, "label": label, "total": len(rows),
            "covered": len(covered), "broken": len(broken),
            "downstream_types": list(downstream),
            "meaning": STEP_MEANING[kind],
            "broken_pages": [{"slug": p["slug"], "title": p["title"],
                              "status": p["idea_status"] or p["result_status"] or p["status"]}
                             for p in broken],
        })

    return {
        "project": project,
        "pages_in_scope": len(scoped),
        "pages_in_vault": len(pages),
        "counts": dict(sorted(counts.items())),
        "steps": steps,
        "blind_spot": ("只认 `[[wikilink]]`。用散文写的关联看不见，所以「断了」= 没找到 wikilink，"
                       "不等于这件事没做过。"),
    }


def render_map(data: dict[str, Any]) -> str:
    scope = data["project"] or "全部项目"
    lines = [f"# 研究链条 · {scope}", "",
             f"> 库里 {data['pages_in_vault']} 页，属于这个范围的 {data['pages_in_scope']} 页。"
             f"这份只回答一件事：**链条在哪一环断了。**", ""]
    flow = "  ".join(f"{s['label']} {s['covered']}/{s['total']}" for s in data["steps"])
    lines += [f"```", f"点子 ──→ 实验 ──→ 结果 ──→ 可引用", f"{flow}", "```", ""]
    lines += ["| 这一环 | 有下游 | 断了 | 断了是什么意思 |", "|---|---:|---:|---|"]
    for step in data["steps"]:
        lines.append(f"| {step['label']} | {step['covered']} | **{step['broken']}** | {step['meaning']} |")
    lines.append("")
    for step in data["steps"]:
        if not step["broken_pages"]:
            continue
        lines += [f"## 断在「{step['label']}」的 {step['broken']} 项", ""]
        for row in step["broken_pages"][:12]:
            mark = f"　`{row['status']}`" if row["status"] else ""
            lines.append(f"- {row['title'][:70]}{mark}")
        if step["broken"] > 12:
            lines.append(f"- …… 另外 {step['broken'] - 12} 项（`--json` 看全部）")
        lines.append("")
    lines += ["> 诚实边界：" + data["blind_spot"], ""]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(description="研究链条覆盖：哪个点子还没有对应实验")
    parser.add_argument("--project", default=None)
    parser.add_argument("--vault", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    data = build_map(args.project, vault_root=args.vault)
    print(json.dumps(data, ensure_ascii=False, indent=2, default=sorted) if args.json
          else render_map(data))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


__all__ = ["build_map", "render_map", "scan_pages", "CHAIN"]
