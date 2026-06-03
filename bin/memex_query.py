#!/usr/bin/env python3
"""
memex_query.py — Memex v0.2.3 按需查询 CLI

LLM 通过 Bash 主动调,**按需查询按需注入** — 取代 v0.2.1 把整个 INDEX
全量 @import 进 ctx 的做法,大幅降低基线 ctx 占用。

子命令:
  --list                                  # 列所有 active project(简洁清单)
  --project <key>                         # 看某 project 的元数据 + 分支 + feedback + reference
  --branch <key> <slug>                   # 拿某分支 memory 路径(找不到 → exit 1)
  --feedback [--project <key>] [--term T] # 列 feedback(全局 / 项目专属 / 含关键词)
  --reference [--project <key>] [--term T]
  --grep <term>                           # 跨索引(name + description)模糊查
  --recent [--days N]                     # 最近 N 天 access 过的(默认 7)
  --health                                # 索引完整性自检

格式:
  默认 markdown(给 LLM 直接读);--json 给脚本管道用

设计原则:
  · 失败 exit 非 0 + stderr 错误(LLM 看得到)
  · 只读 _index/*.jsonl,不动文件状态
  · jq O(1)/O(N) 查询,千级数据 < 50ms
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HOME = Path.home()
DEFAULT_MEMEX = HOME / ".claude/memex"


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


def has_content(memex: Path, key: str) -> bool:
    pdir = memex / "projects" / key
    if not pdir.is_dir():
        return False
    for md in pdir.rglob("*.md"):
        if md.name != "INDEX.md":
            return True
    return False


def parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def short(s: str, n: int = 80) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


# ── 子命令实现 ────────────────────────────────────────────────────

def cmd_list(memex: Path, as_json: bool, active_only: bool = True) -> int:
    projects = load_jsonl(memex / "_index/projects.jsonl")
    if active_only:
        projects = [p for p in projects if has_content(memex, p["key"])]

    if as_json:
        print(json.dumps(projects, ensure_ascii=False, indent=2))
        return 0

    if not projects:
        print("(no active projects — 还没有任何项目有内容)")
        return 0

    print(f"# Active Memex 项目({len(projects)} 个)\n")
    print("| key | display | origin | branches | last_access |")
    print("|---|---|---|---|---|")
    for p in sorted(projects, key=lambda x: x.get("last_access", ""), reverse=True):
        print(
            f"| `{p['key']}` | {p.get('display_name', '?')} "
            f"| `{short(p.get('origin') or '(no origin)', 40)}` "
            f"| {p.get('branch_count', 0)} "
            f"| {p.get('last_access', '?')[:10]} |"
        )
    print()
    print("用 `memex_query.py --project <key>` 看项目详情")
    return 0


def cmd_project(memex: Path, key: str, as_json: bool) -> int:
    projects = {p["key"]: p for p in load_jsonl(memex / "_index/projects.jsonl")}
    info = projects.get(key)
    if not info:
        print(f"✗ 未知 project key: {key}", file=sys.stderr)
        print(f"  跑 `memex_query.py --list` 看可用 key", file=sys.stderr)
        return 1

    branches = [b for b in load_jsonl(memex / "_index/branches.jsonl") if b["project_key"] == key]
    metas = [m for m in load_jsonl(memex / "_index/meta.jsonl") if m.get("project_key") == key]

    project_docs = [m for m in metas if m["type"] in ("project", "overview")]
    feedback = [m for m in metas if m["type"] == "feedback"]
    reference = [m for m in metas if m["type"] == "reference"]

    if as_json:
        result = {
            "project": info,
            "branches": branches,
            "project_docs": project_docs,
            "feedback": feedback,
            "reference": reference,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"# {info.get('display_name', key)}\n")
    print(f"- **key**: `{key}`")
    print(f"- **origin**: `{info.get('origin') or '(none)'}`")
    if info.get("tags"):
        print(f"- **tags**: {', '.join(info['tags'])}")
    print(f"- **last_access**: {info.get('last_access', '?')}")
    print(f"- **branch_count**: {len(branches)}\n")

    print(f"## 分支记忆({len(branches)})\n")
    if branches:
        for b in sorted(branches, key=lambda x: x.get("last_access", ""), reverse=True):
            print(f"- `{b['branch']}` → `{memex}/{b['memory_path']}`")
    else:
        print("(no branch memory)")
    print()

    print(f"## 项目长期决策({len(project_docs)})\n")
    for m in sorted(project_docs, key=lambda x: x["path"]):
        print(f"- `{Path(m['path']).stem}` → `{memex}/{m['path']}`")
        if m.get("description"):
            print(f"    {short(m['description'], 120)}")
    if not project_docs:
        print("(none)")
    print()

    if feedback:
        print(f"## 项目专属 feedback({len(feedback)})\n")
        for m in sorted(feedback, key=lambda x: x["path"]):
            print(f"- `{Path(m['path']).stem}` — {short(m.get('description', ''), 100)}")
            print(f"    `{memex}/{m['path']}`")
        print()

    if reference:
        print(f"## 项目专属 reference({len(reference)})\n")
        for m in sorted(reference, key=lambda x: x["path"]):
            print(f"- `{Path(m['path']).stem}` — {short(m.get('description', ''), 100)}")
            print(f"    `{memex}/{m['path']}`")
        print()

    return 0


def cmd_branch(memex: Path, key: str, slug: str, as_json: bool) -> int:
    branches = load_jsonl(memex / "_index/branches.jsonl")
    match = None
    for b in branches:
        if b["project_key"] == key and (b["branch_slug"] == slug or b["branch"] == slug):
            match = b
            break

    if not match:
        if as_json:
            print(json.dumps({"found": False, "key": key, "slug": slug}))
        else:
            print(f"✗ 没找到 branch memory: project={key} slug={slug}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps({"found": True, **match, "full_path": str(memex / match["memory_path"])},
                         ensure_ascii=False))
    else:
        print(str(memex / match["memory_path"]))
    return 0


def cmd_feedback(memex: Path, project: Optional[str], term: Optional[str], as_json: bool) -> int:
    metas = load_jsonl(memex / "_index/meta.jsonl")
    items = [m for m in metas if m["type"] == "feedback"]
    if project:
        items = [m for m in items if m.get("project_key") == project]
    if term:
        t = term.lower()
        items = [m for m in items if t in (m.get("name", "") + " " + m.get("description", "")).lower()]

    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    scope = f"项目 {project}" if project else "全局 + 所有项目"
    if term:
        scope += f" · 关键词「{term}」"
    print(f"# Feedback({scope}) — {len(items)} 条\n")
    for m in sorted(items, key=lambda x: x["path"]):
        print(f"- `{Path(m['path']).stem}` — {short(m.get('description', ''), 120)}")
        print(f"    `{memex}/{m['path']}`")
    return 0


def cmd_reference(memex: Path, project: Optional[str], term: Optional[str], as_json: bool) -> int:
    metas = load_jsonl(memex / "_index/meta.jsonl")
    items = [m for m in metas if m["type"] == "reference"]
    if project:
        items = [m for m in items if m.get("project_key") == project]
    if term:
        t = term.lower()
        items = [m for m in items if t in (m.get("name", "") + " " + m.get("description", "")).lower()]

    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    scope = f"项目 {project}" if project else "全局 + 所有项目"
    if term:
        scope += f" · 关键词「{term}」"
    print(f"# Reference({scope}) — {len(items)} 条\n")
    for m in sorted(items, key=lambda x: x["path"]):
        print(f"- `{Path(m['path']).stem}` — {short(m.get('description', ''), 120)}")
        print(f"    `{memex}/{m['path']}`")
    return 0


def cmd_grep(memex: Path, term: str, as_json: bool) -> int:
    if not term:
        print("✗ --grep 需要关键词", file=sys.stderr)
        return 2
    metas = load_jsonl(memex / "_index/meta.jsonl")
    t = term.lower()
    hits = []
    for m in metas:
        haystack = " ".join([m.get("name", ""), m.get("description", ""), m.get("path", "")]).lower()
        if t in haystack:
            hits.append(m)

    if as_json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0

    print(f"# Grep 「{term}」 — {len(hits)} 条命中\n")
    for m in sorted(hits, key=lambda x: x["path"]):
        print(f"- [{m['type']}] `{Path(m['path']).stem}` — {short(m.get('description', ''), 120)}")
        if m.get("project_key"):
            print(f"    project={m['project_key']} · `{memex}/{m['path']}`")
        else:
            print(f"    `{memex}/{m['path']}`")
    return 0


def cmd_recent(memex: Path, days: int, as_json: bool) -> int:
    metas = load_jsonl(memex / "_index/meta.jsonl")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    hits = []
    for m in metas:
        la = parse_iso(m.get("last_access", ""))
        if la and la >= cutoff:
            hits.append(m)

    if as_json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0

    print(f"# Recently accessed(最近 {days} 天)— {len(hits)} 条\n")
    for m in sorted(hits, key=lambda x: x.get("last_access", ""), reverse=True):
        print(f"- [{m['type']}] `{Path(m['path']).stem}` · last={m.get('last_access', '?')[:10]}")
        print(f"    {short(m.get('description', ''), 100)} — `{memex}/{m['path']}`")
    return 0


def cmd_health(memex: Path, as_json: bool) -> int:
    """索引完整性自检。"""
    result = {
        "memex_root": str(memex),
        "memex_exists": memex.is_dir(),
        "indices": {},
        "warnings": [],
    }
    for name in ("projects.jsonl", "branches.jsonl", "meta.jsonl"):
        p = memex / "_index" / name
        rows = load_jsonl(p)
        result["indices"][name] = {"path": str(p), "exists": p.exists(), "rows": len(rows)}

    # branches.jsonl 引用的文件是否真存在?
    branches = load_jsonl(memex / "_index/branches.jsonl")
    missing_branches = [b["memory_path"] for b in branches
                        if not (memex / b["memory_path"]).is_file()]
    if missing_branches:
        result["warnings"].append({
            "kind": "missing_branch_files",
            "count": len(missing_branches),
            "examples": missing_branches[:3],
        })

    # meta.jsonl 引用的文件?
    metas = load_jsonl(memex / "_index/meta.jsonl")
    missing_metas = [m["path"] for m in metas if not (memex / m["path"]).is_file()]
    if missing_metas:
        result["warnings"].append({
            "kind": "missing_meta_files",
            "count": len(missing_metas),
            "examples": missing_metas[:3],
        })

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("# Memex 健康自检\n")
        print(f"- memex 根:`{memex}`(exists={result['memex_exists']})\n")
        print("## 索引\n")
        for name, info in result["indices"].items():
            print(f"- `{name}`:{info['rows']} 行")
        print()
        if result["warnings"]:
            print("## ⚠️ 警告\n")
            for w in result["warnings"]:
                print(f"- **{w['kind']}**:{w['count']} 条 — 例:`{w['examples']}`")
            print("\n修复:`python3 ~/.claude/bin/rebuild_index.py`")
        else:
            print("✅ 所有索引引用的文件都存在\n")

    return 0 if not result["warnings"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--memex", default=str(DEFAULT_MEMEX), help="memex 根(默认 ~/.claude/memex)")
    parser.add_argument("--json", action="store_true", help="JSON 输出(给脚本管道用)")

    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="列所有 active project")
    g.add_argument("--all-projects", action="store_true", help="列所有 project(含空 stub)")
    g.add_argument("--project", metavar="KEY", help="查某 project 的详情")
    g.add_argument("--branch", nargs=2, metavar=("KEY", "SLUG"), help="拿某分支 memory 路径")
    g.add_argument("--feedback", action="store_true", help="列 feedback")
    g.add_argument("--reference", action="store_true", help="列 reference")
    g.add_argument("--grep", metavar="TERM", help="跨索引模糊查")
    g.add_argument("--recent", action="store_true", help="最近 access 过的")
    g.add_argument("--health", action="store_true", help="索引完整性自检")

    parser.add_argument("--term", help="(配合 --feedback / --reference)关键词过滤")
    parser.add_argument("--project-filter", dest="project_filter",
                        help="(配合 --feedback / --reference)只看该 project")
    parser.add_argument("--days", type=int, default=7, help="(配合 --recent)天数,默认 7")

    args = parser.parse_args()

    memex = Path(args.memex).expanduser()
    if not memex.is_dir():
        print(f"✗ memex 根不存在:{memex}", file=sys.stderr)
        return 2

    if args.list:
        return cmd_list(memex, args.json, active_only=True)
    if args.all_projects:
        return cmd_list(memex, args.json, active_only=False)
    if args.project:
        return cmd_project(memex, args.project, args.json)
    if args.branch:
        return cmd_branch(memex, args.branch[0], args.branch[1], args.json)
    if args.feedback:
        return cmd_feedback(memex, args.project_filter, args.term, args.json)
    if args.reference:
        return cmd_reference(memex, args.project_filter, args.term, args.json)
    if args.grep:
        return cmd_grep(memex, args.grep, args.json)
    if args.recent:
        return cmd_recent(memex, args.days, args.json)
    if args.health:
        return cmd_health(memex, args.json)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
