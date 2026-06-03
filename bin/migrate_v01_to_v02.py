#!/usr/bin/env python3
"""
migrate_v01_to_v02.py — Memex v0.1 → v0.2 迁移(通用版)

把旧 ~/.claude/projects/<cwd-slug>/memory/{projects,feedback,reference,global}/**
搬到新 ~/.claude/memex/{global,projects/<key>}/**,并建 3 个 jsonl 索引。

特点:
  · YAML mapping 驱动:用户在 mapping.yaml 声明 biz_dir → repo_path
  · 默认 dry-run,--apply 才真动
  · copy 不 move:旧文件原地保留
  · 写前备份:~/.claude/memex.pre-apply-backup-<ts>/

Usage:
  migrate_v01_to_v02.py --source <v01-mem-root> --mapping <yaml>
  migrate_v01_to_v02.py --source <v01-mem-root> --mapping <yaml> --apply

mapping yaml 示例见:examples/migrate-mapping.example.yaml
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HOME = Path.home()
DEST = HOME / ".claude/memex"
DERIVE_KEY = HOME / ".claude/bin/derive_project_key.py"

# ── 运行时由 --mapping 加载 ────────────────────────────────────────
BIZ_TO_REPO: dict = {}
FEEDBACK_TO_GLOBAL: bool = True
REFERENCE_PROJECT_OVERRIDES: dict = {}


def load_mapping(yaml_path: str) -> None:
    global BIZ_TO_REPO, FEEDBACK_TO_GLOBAL, REFERENCE_PROJECT_OVERRIDES
    try:
        import yaml
    except ImportError:
        print("[migrate] PyYAML 未装。pip install pyyaml", file=sys.stderr)
        sys.exit(2)
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    raw = data.get("biz_to_repo") or {}
    BIZ_TO_REPO = {k: (str(Path(v).expanduser()) if v and not v.startswith("__group__") else v)
                   for k, v in raw.items()}
    FEEDBACK_TO_GLOBAL = data.get("feedback_to_global", True)
    REFERENCE_PROJECT_OVERRIDES = data.get("reference_project_overrides") or {}


def derive_key_for_repo(repo_path: str) -> Optional[dict]:
    if not Path(repo_path).is_dir():
        return None
    try:
        out = subprocess.run(
            ["python3", str(DERIVE_KEY), repo_path],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return json.loads(out.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return None


class Plan:
    def __init__(self):
        self.copies: list[tuple[Path, Path, str]] = []
        self.skipped: list[tuple[Path, str]] = []
        self.projects: dict[str, dict] = {}
        self.errors: list[str] = []

    def add_copy(self, src: Path, dest: Path, type_: str):
        self.copies.append((src, dest, type_))

    def add_project(self, info: dict, tags: Optional[list] = None):
        key = info["key"]
        if key not in self.projects:
            self.projects[key] = {
                "key": key,
                "display_name": info["display_name"],
                "origin": info["origin"],
                "origin_aliases": info.get("origin_aliases", []),
                "repo_paths_seen": [info["repo_root"]] if info["repo_root"] else [],
                "tags": tags or [],
                "first_seen": now_iso(),
                "last_access": now_iso(),
                "status": "active",
                "branch_count": 0,
            }


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def file_sha256(p: Path) -> str:
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def parse_frontmatter(p: Path) -> dict:
    out = {"name": p.stem, "description": ""}
    try:
        with open(p, "r", encoding="utf-8") as f:
            head = f.read(2048)
    except OSError:
        return out
    if not head.startswith("---"):
        return out
    try:
        end = head.index("\n---", 3)
    except ValueError:
        return out
    block = head[3:end]
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            out["name"] = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            out["description"] = line.split(":", 1)[1].strip().strip('"').strip("'")
    return out


def build_plan(source: Path) -> Plan:
    plan = Plan()
    biz_key: dict[str, str] = {}

    for biz, repo in BIZ_TO_REPO.items():
        if repo == "__group__" or (isinstance(repo, str) and repo.startswith("__group__")):
            continue
        if not repo:
            plan.errors.append(f"{biz}: mapping 未指定 repo,跳过")
            continue
        info = derive_key_for_repo(repo)
        if not info or not info.get("is_git"):
            plan.errors.append(f"{biz}: derive_key 失败({repo}),跳过")
            continue
        biz_key[biz] = info["key"]
        plan.add_project(info)

    # projects/ 下文件
    proj_src = source / "projects"
    if proj_src.is_dir():
        for md in proj_src.rglob("*.md"):
            rel = md.relative_to(proj_src)
            parts = rel.parts
            biz_match: Optional[str] = None
            for cand in ["/".join(parts[:i]) for i in range(min(3, len(parts)), 0, -1)]:
                if cand in BIZ_TO_REPO:
                    biz_match = cand
                    break
            if not biz_match:
                plan.errors.append(f"未匹配 biz: {rel}")
                continue

            repo_kind = BIZ_TO_REPO[biz_match]
            is_branch = (len(parts) >= len(biz_match.split("/")) + 1
                         and parts[len(biz_match.split("/"))] == "branches")

            if repo_kind == "__group__" or (isinstance(repo_kind, str) and repo_kind.startswith("__group__")):
                sub = ""
                if isinstance(repo_kind, str) and repo_kind.startswith("__group__/"):
                    sub = repo_kind[len("__group__/"):]
                rest = rel.relative_to(biz_match)
                dest_rel = Path("global") / biz_match.split("/")[0] / sub / rest
                plan.add_copy(md, DEST / dest_rel, "group")
            else:
                key = biz_key.get(biz_match)
                if not key:
                    plan.skipped.append((md, f"无 key:{biz_match}"))
                    continue
                rest = rel.relative_to(biz_match)
                dest_rel = Path("projects") / key / rest
                plan.add_copy(md, DEST / dest_rel, "branch" if is_branch else "project")
                if is_branch:
                    plan.projects[key]["branch_count"] += 1

    # feedback / reference / global / user
    for top in ["feedback", "reference", "global", "user"]:
        src_dir = source / top
        if not src_dir.is_dir():
            continue
        for md in src_dir.glob("*.md"):
            fname = md.name
            if top == "reference" and fname in REFERENCE_PROJECT_OVERRIDES:
                biz = REFERENCE_PROJECT_OVERRIDES[fname]
                key = biz_key.get(biz)
                if not key:
                    plan.skipped.append((md, f"reference override but no key({biz})"))
                    continue
                dest_rel = Path("projects") / key / "reference" / fname
                plan.add_copy(md, DEST / dest_rel, "reference")
            elif top == "global":
                dest_rel = Path("global") / fname
                plan.add_copy(md, DEST / dest_rel, top)
            else:
                dest_rel = Path("global") / top / fname
                plan.add_copy(md, DEST / dest_rel, top)

    return plan


def execute(plan: Plan, apply: bool) -> None:
    print(f"\n{'='*60}\nMemex v0.1 → v0.2 迁移 plan\n{'='*60}\n")

    print(f"项目识别({len(plan.projects)}):")
    for key, info in plan.projects.items():
        print(f"  · {key}")
        print(f"      origin = {info['origin']}")

    print(f"\n文件 copy({len(plan.copies)}):")
    by_dest_parent: dict[str, list[tuple[Path, Path]]] = {}
    for src, dest, type_ in plan.copies:
        parent = str(dest.parent.relative_to(DEST))
        by_dest_parent.setdefault(parent, []).append((src, dest))
    for parent in sorted(by_dest_parent.keys()):
        print(f"\n  → memex/{parent}/  ({len(by_dest_parent[parent])} 文件)")
        for src, dest in sorted(by_dest_parent[parent], key=lambda x: x[1].name):
            indicator = "  "
            if dest.exists():
                indicator = "= " if file_sha256(src) == file_sha256(dest) else "! "
            print(f"      {indicator}{src.name}")

    if plan.skipped:
        print(f"\n跳过({len(plan.skipped)}):")
        for src, reason in plan.skipped:
            print(f"  ⚠️  {src}: {reason}")

    if plan.errors:
        print(f"\n错误({len(plan.errors)}):")
        for e in plan.errors:
            print(f"  ✗ {e}")

    if not apply:
        print("\n(dry-run)  实际执行加 --apply")
        return

    print(f"\n{'='*60}\n开始执行(--apply)\n{'='*60}\n")

    if DEST.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = HOME / f".claude/memex.pre-apply-backup-{ts}"
        print(f"备份: cp -a {DEST} {backup}")
        shutil.copytree(DEST, backup)

    for sub in ["_index", "global/feedback", "global/reference", "global/user", "projects"]:
        (DEST / sub).mkdir(parents=True, exist_ok=True)

    copied = skipped = 0
    for src, dest, type_ in plan.copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and file_sha256(src) == file_sha256(dest):
            skipped += 1
            continue
        shutil.copy2(src, dest)
        copied += 1
    print(f"✓ 文件 copy 完成: {copied} 新建 / {skipped} 跳过(同 sha)\n")

    # 直接调 rebuild_index 重建 3 个 jsonl
    rebuild = HOME / ".claude/bin/rebuild_index.py"
    if rebuild.exists():
        subprocess.run(["python3", str(rebuild), "--memex", str(DEST)], check=False)
    update_idx = HOME / ".claude/bin/update_index_md.py"
    if update_idx.exists():
        subprocess.run(["python3", str(update_idx), "--memex", str(DEST)], check=False)

    print(f"\n完成 ✓")
    print(f"  memex 根: {DEST}")
    print(f"  旧池保留(等 LRU 自然回收)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source", required=True, help="v0.1 mem_root,如 ~/.claude/projects/<slug>/memory")
    parser.add_argument("--mapping", required=True, help="YAML mapping(见 examples/migrate-mapping.example.yaml)")
    args = parser.parse_args()

    load_mapping(args.mapping)

    source = Path(args.source).expanduser()
    if not source.is_dir():
        print(f"✗ source 不存在: {source}", file=sys.stderr)
        return 2

    plan = build_plan(source)
    execute(plan, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
