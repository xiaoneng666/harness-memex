#!/usr/bin/env python3
"""
rebuild_index.py — Memex v0.2 索引重建

扫 ~/.claude/memex/**/*.md → 重建 3 个 jsonl:
  · _index/meta.jsonl       全部文件,LRU 用
  · _index/branches.jsonl   分支记忆专用倒排
  · _index/projects.jsonl   项目元数据(优先沿用现有)

LRU 字段(last_access / decay / status)从旧 meta.jsonl 保留;新文件用 mtime 兜底。

Usage:
  rebuild_index.py                       # 扫 ~/.claude/memex/
  rebuild_index.py --memex <path>        # 指定 memex 根
  rebuild_index.py --memex <path> --no-rewrite-projects   # projects.jsonl 不动
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HOME = Path.home()
DEFAULT_MEMEX = HOME / ".claude/memex"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mtime_iso(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_frontmatter(p: Path) -> dict:
    """提取 name / description / type / project_key / branch。"""
    out = {"name": p.stem, "description": "", "type": "", "project_key": "", "branch": ""}
    try:
        with open(p, "r", encoding="utf-8") as f:
            head = f.read(4096)
    except OSError:
        return out
    if not head.startswith("---"):
        return out
    try:
        end = head.index("\n---", 3)
    except ValueError:
        return out
    block = head[3:end]

    def grab_line(key: str) -> Optional[str]:
        m = re.search(rf'^{key}:\s*(.*)$', block, re.MULTILINE)
        if not m:
            return None
        v = m.group(1).strip().strip('"').strip("'")
        return v

    for k in ("name", "description"):
        v = grab_line(k)
        if v is not None:
            out[k] = v

    # type 优先 metadata.type
    nested = re.search(r'^metadata:\s*\n((?:[ \t]+\w+:.*\n?)+)', block, re.MULTILINE)
    if nested:
        for k in ("type", "project_key", "branch"):
            m = re.search(rf'^[ \t]+{k}:\s*(\S+)', nested.group(1), re.MULTILINE)
            if m:
                out[k] = m.group(1).strip().strip('"').strip("'")
    if not out["type"]:
        v = grab_line("type")
        if v:
            out["type"] = v
    return out


def infer_type_from_path(rel: str) -> str:
    """frontmatter 缺 type 时,从路径推断兜底。"""
    parts = rel.split("/")
    if parts[0] == "projects" and len(parts) >= 3:
        if len(parts) >= 4 and parts[2] == "branches":
            return "branch"
        if parts[2] == "feedback":
            return "feedback"
        if parts[2] == "reference":
            return "reference"
        return "project"
    if parts[0] == "global":
        if len(parts) >= 2 and parts[1] in ("feedback", "reference", "user"):
            return parts[1]
        return "global"
    return ""


def infer_project_branch(rel: str) -> tuple[str, str]:
    """从路径推断 project_key + branch。"""
    parts = rel.split("/")
    if parts[0] == "projects" and len(parts) >= 4 and parts[2] == "branches":
        project_key = parts[1]
        branch_slug = parts[3].rsplit(".md", 1)[0]
        return project_key, branch_slug
    if parts[0] == "projects" and len(parts) >= 2:
        return parts[1], ""
    return "", ""


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    rows: list[dict] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def atomic_write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".rebuild_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ── 主流程 ────────────────────────────────────────────────────────
def rebuild(memex: Path, rewrite_projects: bool = True) -> dict:
    idx_dir = memex / "_index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    meta_path = idx_dir / "meta.jsonl"
    branches_path = idx_dir / "branches.jsonl"
    projects_path = idx_dir / "projects.jsonl"

    old_meta = {r["path"]: r for r in load_jsonl(meta_path) if "path" in r}
    old_projects = {r["key"]: r for r in load_jsonl(projects_path) if "key" in r}

    metas: list[dict] = []
    branches: list[dict] = []
    project_seen: dict[str, int] = {}

    skip_dirs = {"_index", "_trash", "_archive"}
    for md in memex.rglob("*.md"):
        # 跳过 _index/* _trash/* _archive/*
        if any(part in skip_dirs for part in md.relative_to(memex).parts):
            continue
        if md.name in ("INDEX.md",):
            # INDEX.md 也入 meta(类型=index),但不进 branches
            pass

        rel = str(md.relative_to(memex))
        fm = parse_frontmatter(md)
        # 路径优先(无歧义),frontmatter type 当 fallback。旧 v0.1 文件
        # 经常有 type:project 但实际是 branch,路径才是 ground truth。
        path_type = infer_type_from_path(rel)
        ftype = path_type or fm["type"]
        if md.name == "INDEX.md":
            ftype = "index"
        project_key = fm["project_key"]
        branch_slug = fm["branch"]
        if not project_key or not branch_slug:
            pk, bs = infer_project_branch(rel)
            project_key = project_key or pk
            branch_slug = branch_slug or bs

        size = md.stat().st_size
        old = old_meta.get(rel, {})
        last_access = old.get("last_access") or mtime_iso(md)
        decay = old.get("decay", 0)
        status = old.get("status", "active")

        metas.append({
            "path": rel,
            "type": ftype,
            "project_key": project_key,
            "branch": branch_slug,
            "name": fm["name"],
            "description": fm["description"],
            "status": status,
            "last_access": last_access,
            "decay": decay,
            "size": size,
        })

        if ftype == "branch" and project_key and branch_slug:
            old_b: dict = {}
            # 尝试从旧 branches 拿(可选,这里不必)
            branches.append({
                "project_key": project_key,
                "branch": branch_slug,
                "branch_slug": branch_slug,
                "memory_path": rel,
                "status": status,
                "last_access": last_access,
                "decay": decay,
                "size": size,
                "alive_on_remote": old_b.get("alive_on_remote", True),
                "alive_locally": old_b.get("alive_locally", True),
            })
            project_seen[project_key] = project_seen.get(project_key, 0) + 1
        elif project_key:
            project_seen.setdefault(project_key, 0)

    # 稳定排序(idempotent)
    metas.sort(key=lambda r: r["path"])
    branches.sort(key=lambda r: (r["project_key"], r["branch"]))

    atomic_write_jsonl(meta_path, metas)
    atomic_write_jsonl(branches_path, branches)

    # projects.jsonl:沿用旧值,只更新 branch_count + last_access
    if rewrite_projects:
        projects_out: list[dict] = []
        for key, info in old_projects.items():
            info = dict(info)
            info["branch_count"] = project_seen.get(key, 0)
            if key in project_seen:
                info.setdefault("last_access", now_iso())
            projects_out.append(info)
        # 加新发现的 project_key(在 meta 里出现但 projects.jsonl 没有)
        for key in project_seen:
            if key not in old_projects:
                projects_out.append({
                    "key": key,
                    "display_name": key.split("-", 1)[-1] if "-" in key else key,
                    "origin": "",
                    "origin_aliases": [],
                    "repo_paths_seen": [],
                    "tags": [],
                    "first_seen": now_iso(),
                    "last_access": now_iso(),
                    "status": "active",
                    "branch_count": project_seen[key],
                })
        projects_out.sort(key=lambda r: r["key"])
        atomic_write_jsonl(projects_path, projects_out)

    return {
        "meta": len(metas),
        "branches": len(branches),
        "projects": len(project_seen),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--memex", default=str(DEFAULT_MEMEX), help="memex root (default: ~/.claude/memex)")
    parser.add_argument("--no-rewrite-projects", action="store_true", help="不重写 projects.jsonl")
    # 兼容老调用:rebuild_index.py <path> 当 memex 根
    parser.add_argument("positional", nargs="?", help=argparse.SUPPRESS)
    args = parser.parse_args()

    memex = Path(args.positional or args.memex)

    # 老 hook 可能传旧 mem_root(.../memory/),不在 memex 根 → 兼容静默退出
    if memex.name == "memory" and not (memex / "global").is_dir():
        # 这是 v0.1 mem_root,新版不处理,等 LRU 回收
        print(f"⚠️ v0.1 mem_root 跳过(等 LRU 自然回收): {memex}", file=sys.stderr)
        return 0

    if not memex.is_dir():
        print(f"❌ memex 根不存在: {memex}", file=sys.stderr)
        return 1

    stats = rebuild(memex, rewrite_projects=not args.no_rewrite_projects)
    print(f"✅ rebuild_index 完成:")
    print(f"   · meta.jsonl       {stats['meta']} 行")
    print(f"   · branches.jsonl   {stats['branches']} 行")
    print(f"   · projects.jsonl   {stats['projects']} 项(更新 branch_count)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
