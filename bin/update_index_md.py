#!/usr/bin/env python3
"""
update_index_md.py — Memex v0.2 INDEX.md 自动重写

从 _index/{meta,branches,projects}.jsonl 重写:
  · ~/.claude/memex/global/INDEX.md          顶层全局门面
  · ~/.claude/memex/projects/<key>/INDEX.md  每项目门面

只重写 <!-- AUTO:START <name> --> ... <!-- AUTO:END <name> --> 标记区块,其余内容保留。
缺标记区块 → 用对应模板新建。

Usage:
  update_index_md.py                  # 全跑
  update_index_md.py --global         # 只跑 global/INDEX.md
  update_index_md.py --project <key>  # 只跑某 project
  update_index_md.py --memex <path>   # 指定 memex 根
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HOME = Path.home()
DEFAULT_MEMEX = HOME / ".claude/memex"
GLOBAL_TEMPLATE = HOME / ".claude/MEMEX_GLOBAL_INDEX_TEMPLATE.md"
PROJECT_TEMPLATE = HOME / ".claude/MEMEX_PROJECT_INDEX_TEMPLATE.md"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out: list[dict] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def short_desc(r: dict, max_chars: int = 90) -> str:
    d = (r.get("description") or "").strip()
    if not d:
        return r.get("name") or Path(r.get("path", "")).stem
    if len(d) > max_chars:
        d = d[:max_chars].rstrip() + "..."
    return d


def atomic_write_text(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".update_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ── 区块渲染 ───────────────────────────────────────────────────────
def render_project_table(projects: list[dict], metas_by_key: dict[str, list[dict]]) -> str:
    if not projects:
        return "_(no projects yet)_\n"
    lines = ["| 项目 | 分支数 | origin | 关键文档 |", "|---|---|---|---|"]
    for p in sorted(projects, key=lambda x: x["display_name"].lower()):
        key = p["key"]
        docs = metas_by_key.get(key, [])
        proj_docs = [m for m in docs if m["type"] in ("project", "overview")][:3]
        # global/INDEX.md 位于 memex/global/,目标在 memex/projects/<key>/...
        # 相对路径 = ../<m['path']>(m['path'] 已含 projects/<key>/...)
        doc_str = " · ".join(f"[`{Path(m['path']).stem}`](../{m['path']})" for m in proj_docs) or "—"
        origin = p.get("origin") or "(no origin)"
        lines.append(f"| **{p['display_name']}** | {p.get('branch_count', 0)} | `{origin}` | {doc_str} |")
    return "\n".join(lines) + "\n"


def render_link_list(records: list[dict], base_dir: str) -> str:
    """渲染成「· [`name`](path) — desc · ...」一行链接列表。"""
    if not records:
        return "_(empty)_\n"
    parts = []
    for r in sorted(records, key=lambda x: x["path"]):
        rel = r["path"]
        # 相对 base_dir 算 link
        try:
            link = os.path.relpath(rel, base_dir)
        except ValueError:
            link = rel
        name = Path(rel).stem
        d = short_desc(r)
        parts.append(f"[`{name}`]({link}) — {d}")
    return " · ".join(parts) + "\n"


def render_branch_list(branches: list[dict]) -> str:
    if not branches:
        return "_(no branches)_\n"
    parts = []
    for b in sorted(branches, key=lambda x: x["branch"]):
        slug = b["branch_slug"]
        # branches/<slug>.md 相对项目 INDEX 的链接
        link = f"branches/{slug}.md"
        parts.append(f"[`{b['branch']}`]({link})")
    return " · ".join(parts) + "\n"


# ── 替换 / 创建 ────────────────────────────────────────────────────
AUTO_PATTERN = re.compile(
    r"<!--\s*AUTO:START\s+([a-z0-9_-]+)\s*-->(.*?)<!--\s*AUTO:END\s+\1\s*-->",
    re.DOTALL,
)


def replace_auto_blocks(text: str, replacements: dict[str, str]) -> tuple[str, list[str]]:
    """把 text 里每个 AUTO 区块替换成对应内容。返回 (new_text, missing_blocks)。"""
    found: set[str] = set()

    def sub(m: re.Match) -> str:
        name = m.group(1)
        found.add(name)
        if name in replacements:
            return f"<!-- AUTO:START {name} -->\n{replacements[name]}<!-- AUTO:END {name} -->"
        return m.group(0)

    new_text = AUTO_PATTERN.sub(sub, text)
    missing = [n for n in replacements if n not in found]
    return new_text, missing


def render_global_index(memex: Path) -> str:
    projects = load_jsonl(memex / "_index/projects.jsonl")
    metas = load_jsonl(memex / "_index/meta.jsonl")

    metas_by_key: dict[str, list[dict]] = {}
    for m in metas:
        if m.get("project_key"):
            metas_by_key.setdefault(m["project_key"], []).append(m)

    g_feedback = [m for m in metas if m["path"].startswith("global/feedback/")]
    g_reference = [m for m in metas if m["path"].startswith("global/reference/")]
    g_misc = [m for m in metas
              if m["path"].startswith("global/")
              and not m["path"].startswith("global/feedback/")
              and not m["path"].startswith("global/reference/")
              and not m["path"].startswith("global/user/")
              and not m["path"].endswith("INDEX.md")]

    replacements = {
        "project-table": "\n" + render_project_table(projects, metas_by_key) + "\n",
        "feedback-list": "\n" + render_link_list(g_feedback, "global") + "\n",
        "reference-list": "\n" + render_link_list(g_reference, "global") + "\n",
        "misc-list": "\n" + render_link_list(g_misc, "global") + "\n",
    }

    index_path = memex / "global/INDEX.md"
    if not index_path.exists():
        template = GLOBAL_TEMPLATE.read_text(encoding="utf-8") if GLOBAL_TEMPLATE.exists() else "# Memex Global\n"
        index_path.write_text(template, encoding="utf-8")

    text = index_path.read_text(encoding="utf-8")
    new_text, missing = replace_auto_blocks(text, replacements)
    if missing:
        print(f"⚠️ global/INDEX.md 缺 AUTO 区块: {missing}", file=sys.stderr)
    atomic_write_text(index_path, new_text)
    return str(index_path)


def render_project_index(memex: Path, project_key: str) -> str:
    projects = {p["key"]: p for p in load_jsonl(memex / "_index/projects.jsonl")}
    branches = [b for b in load_jsonl(memex / "_index/branches.jsonl") if b["project_key"] == project_key]
    metas = [m for m in load_jsonl(memex / "_index/meta.jsonl") if m.get("project_key") == project_key]

    info = projects.get(project_key)
    if not info:
        print(f"⚠️ project {project_key} 不在 projects.jsonl", file=sys.stderr)
        info = {"key": project_key, "display_name": project_key, "origin": "(unknown)"}

    project_docs = [m for m in metas if m["type"] in ("project", "overview")]
    project_feedback = [m for m in metas if m["type"] == "feedback"]
    project_reference = [m for m in metas if m["type"] == "reference"]

    replacements = {
        "branch-list": "\n" + render_branch_list(branches) + "\n",
        "project-docs": "\n" + render_link_list(project_docs, f"projects/{project_key}") + "\n",
        "project-feedback": "\n" + render_link_list(project_feedback, f"projects/{project_key}") + "\n",
        "project-reference": "\n" + render_link_list(project_reference, f"projects/{project_key}") + "\n",
    }

    index_path = memex / "projects" / project_key / "INDEX.md"
    if not index_path.exists():
        template_text = PROJECT_TEMPLATE.read_text(encoding="utf-8") if PROJECT_TEMPLATE.exists() else "# {{DISPLAY_NAME}}\n"
        seeded = (template_text
                  .replace("{{DISPLAY_NAME}}", info.get("display_name", project_key))
                  .replace("{{KEY}}", project_key)
                  .replace("{{ORIGIN}}", info.get("origin") or "(no origin)"))
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(seeded, encoding="utf-8")

    text = index_path.read_text(encoding="utf-8")
    new_text, missing = replace_auto_blocks(text, replacements)
    if missing:
        print(f"⚠️ projects/{project_key}/INDEX.md 缺 AUTO 区块: {missing}", file=sys.stderr)
    atomic_write_text(index_path, new_text)
    return str(index_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--memex", default=str(DEFAULT_MEMEX))
    parser.add_argument("--global", dest="only_global", action="store_true", help="只跑 global/INDEX.md")
    parser.add_argument("--project", help="只跑某 project key")
    parser.add_argument("positional", nargs="?", help=argparse.SUPPRESS)
    args = parser.parse_args()

    memex = Path(args.positional or args.memex)

    # 兼容 v0.1 调用:传入 mem_root → 静默跳过
    if memex.name == "memory" and not (memex / "global").is_dir():
        print(f"⚠️ v0.1 mem_root 跳过: {memex}", file=sys.stderr)
        return 0

    if not memex.is_dir():
        print(f"❌ memex 根不存在: {memex}", file=sys.stderr)
        return 1

    if args.project:
        p = render_project_index(memex, args.project)
        print(f"✅ {p}")
        return 0

    if args.only_global:
        p = render_global_index(memex)
        print(f"✅ {p}")
        return 0

    # 全跑
    p = render_global_index(memex)
    print(f"✅ {p}")
    projects = load_jsonl(memex / "_index/projects.jsonl")
    for proj in projects:
        p = render_project_index(memex, proj["key"])
        print(f"✅ {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
