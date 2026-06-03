#!/usr/bin/env python3
"""
update_memex_bridge.py — Memex v0.2.3 桥 + catalog 更新

主模式(默认):
  · 扫 cwd 子目录(深度 ≤ 4)所有 .git
  · derive_project_key 拿 key + display + origin
  · 确保 memex/projects/<key>/ 骨架 + INDEX.md
  · upsert projects.jsonl
  · 替换 / 追加 MEMORY.md 末尾的 <!-- memex:bridge --> 区块,@import:
      - global/INDEX.md
      - cwd-扫到的 project 中有内容的
      - + projects.jsonl.last_access < 30d 的 project 中有内容的(recently active)
  · 维护 ~/.claude/CLAUDE.md 的 <!-- memex:catalog --> 块(@import global INDEX)
    — env MEMEX_NO_CATALOG=1 opt-out

--touch 模式:
  · 快速 bump projects.jsonl.last_access(hook 触发用),不动 bridge

Usage:
  update_memex_bridge.py --cwd <path> [--memex <path>] [--cc-memory <path>]
  update_memex_bridge.py --touch <project_key> [--repo <path>] [--memex <path>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

HOME = Path.home()
DEFAULT_MEMEX = HOME / ".claude/memex"
DERIVE_KEY = HOME / ".claude/bin/derive_project_key.py"
PROJECT_TEMPLATE = HOME / ".claude/MEMEX_PROJECT_INDEX_TEMPLATE.md"
GLOBAL_TEMPLATE = HOME / ".claude/MEMEX_GLOBAL_INDEX_TEMPLATE.md"

BRIDGE_START = "<!-- memex:bridge:start -->"
BRIDGE_END = "<!-- memex:bridge:end -->"
CATALOG_START = "<!-- memex:catalog:start -->"
CATALOG_END = "<!-- memex:catalog:end -->"

USER_CLAUDE_MD = HOME / ".claude/CLAUDE.md"
RECENT_DAYS = int(os.environ.get("MEMEX_RECENT_DAYS", "30"))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def atomic_write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".bridge_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write_text(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".bridge_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def derive_for_repo(repo_root: str) -> Optional[dict]:
    try:
        res = subprocess.run(
            ["python3", str(DERIVE_KEY), repo_root],
            capture_output=True, text=True, timeout=5,
        )
        if res.returncode == 0:
            return json.loads(res.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        pass
    return None


def discover_repos(cwd: Path, max_depth: int = 4) -> list[dict]:
    """扫 cwd 下所有 .git(深度 ≤ max_depth),返回 derive 后的 info 列表(已去重)。"""
    seen_roots: set[str] = set()
    results: list[dict] = []
    try:
        for git_path in cwd.glob("**/.git"):
            try:
                depth = len(git_path.relative_to(cwd).parts)
            except ValueError:
                continue
            if depth > max_depth:
                continue
            repo_root = str(git_path.parent.resolve())
            if repo_root in seen_roots:
                continue
            seen_roots.add(repo_root)
            info = derive_for_repo(repo_root)
            if info and info.get("is_git") and info.get("key"):
                results.append(info)
    except (OSError, RuntimeError):
        pass
    return results


def ensure_project_skeleton(memex: Path, info: dict) -> bool:
    """确保 memex/projects/<key>/ 骨架存在。返回是否新建。"""
    key = info["key"]
    pdir = memex / "projects" / key
    new = not pdir.exists()
    for sub in ("branches", "feedback", "reference"):
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    index = pdir / "INDEX.md"
    if not index.exists() and PROJECT_TEMPLATE.exists():
        seeded = (PROJECT_TEMPLATE.read_text(encoding="utf-8")
                  .replace("{{DISPLAY_NAME}}", info.get("display_name", key))
                  .replace("{{KEY}}", key)
                  .replace("{{ORIGIN}}", info.get("origin") or "(no origin)"))
        index.write_text(seeded, encoding="utf-8")
    return new


def upsert_projects_jsonl(memex: Path, infos: list[dict]) -> int:
    """把 discovered 的 project 合并进 projects.jsonl,返回新增数。"""
    path = memex / "_index/projects.jsonl"
    existing = {r["key"]: r for r in load_jsonl(path) if "key" in r}
    added = 0
    for info in infos:
        key = info["key"]
        repo_root = info.get("repo_root", "")
        if key in existing:
            # 更新 repo_paths_seen / last_access
            rec = existing[key]
            paths = rec.get("repo_paths_seen", [])
            if repo_root and repo_root not in paths:
                paths.append(repo_root)
                rec["repo_paths_seen"] = paths
            rec["last_access"] = now_iso()
            # 补 origin / aliases(如本来空)
            if not rec.get("origin") and info.get("origin"):
                rec["origin"] = info["origin"]
        else:
            existing[key] = {
                "key": key,
                "display_name": info.get("display_name", key),
                "origin": info.get("origin", ""),
                "origin_aliases": info.get("origin_aliases", []),
                "repo_paths_seen": [repo_root] if repo_root else [],
                "tags": [],
                "first_seen": now_iso(),
                "last_access": now_iso(),
                "status": "active",
                "branch_count": 0,
            }
            added += 1
    rows = sorted(existing.values(), key=lambda r: r["key"])
    atomic_write_jsonl(path, rows)
    return added


def build_bridge_block(memex: Path, keys: list[str]) -> str:
    """v0.2.2 起 bridge 块降级为指示性注释 — 不再 @import 全 INDEX(避免 ctx 爆 +
    /compact 后 MEMORY.md bridge 可能丢失的脆弱依赖)。真正的 catalog 在
    ~/.claude/CLAUDE.md(survive compact),具体内容按需用 memex_query.py 查。
    """
    lines = [BRIDGE_START,
             "<!-- 由 ~/.claude/hooks/session-bootstrap.sh (Memex v0.2.3) 自动维护 -->",
             "<!-- Memex catalog 见 ~/.claude/CLAUDE.md(survive /compact)-->",
             "<!-- 按需查询:python3 ~/.claude/bin/memex_query.py [--list | --project KEY | --branch KEY SLUG | --grep TERM | --health] -->"]
    if keys:
        lines.append(f"<!-- 本 cwd 检测到 {len(keys)} 个 active project,完整目录见 CLAUDE.md catalog -->")
    lines.append(BRIDGE_END)
    return "\n".join(lines) + "\n"


def build_catalog_manifest(memex: Path) -> str:
    """v0.2.2 catalog 极简 manifest — 直接写入项目目录(不 @import 全 INDEX),
    占用 ~2KB,LLM 一眼能看到所有项目 + 怎么按需查具体内容。
    """
    projects = load_jsonl(memex / "_index/projects.jsonl")
    active = [p for p in projects if has_content(memex, p["key"])]
    active.sort(key=lambda p: p.get("last_access", ""), reverse=True)

    lines = [
        CATALOG_START,
        "<!-- 由 ~/.claude/bin/update_memex_bridge.py (Memex v0.2.3) 自动维护 -->",
        "<!-- 永久 opt-out:touch ~/.claude/memex/.no_catalog 或 export MEMEX_NO_CATALOG=1 -->",
        "",
        "# Memex — 按需查询的长期工作面",
        "",
        f"已知 active project 共 **{len(active)}** 个(有内容、最近 30d 内被访问)。**不预载内容,按需查**。",
        "",
        "## 查询入口(LLM 主动用 Bash 调)",
        "",
        "- `python3 ~/.claude/bin/memex_query.py --list` — 列所有 active project",
        "- `python3 ~/.claude/bin/memex_query.py --project <key>` — 看 project 元数据 / 分支 / feedback / reference",
        "- `python3 ~/.claude/bin/memex_query.py --branch <key> <slug>` — 拿分支 memory 路径",
        "- `python3 ~/.claude/bin/memex_query.py --feedback [--project-filter KEY] [--term TERM]` — 列 feedback",
        "- `python3 ~/.claude/bin/memex_query.py --reference [--project-filter KEY] [--term TERM]` — 列 reference",
        "- `python3 ~/.claude/bin/memex_query.py --grep <term>` — 跨索引模糊查",
        "- `python3 ~/.claude/bin/memex_query.py --recent [--days N]` — 最近 access 过的",
        "",
        "## 项目目录(按 last_access 降序)",
        "",
    ]
    if not active:
        lines.append("_(暂无 active project — 一旦碰过某 git repo + 写第一条 memory,即会出现在这里)_")
    else:
        lines.append("| key | display | origin | branches |")
        lines.append("|---|---|---|---|")
        for p in active:
            origin = p.get("origin") or "(none)"
            if len(origin) > 50:
                origin = origin[:48] + "…"
            lines.append(
                f"| `{p['key']}` | {p.get('display_name', '?')} "
                f"| `{origin}` | {p.get('branch_count', 0)} |"
            )
    lines.append("")
    lines.append("## 切分支 / 编辑时")
    lines.append("")
    lines.append("post-checkout-handoff / pre-edit-branch-notice hook 会自动塞具体 memory 路径进 ctx,不用查。")
    lines.append("")
    lines.append("## 写新 memory 时")
    lines.append("")
    lines.append("- 跨项目纪律 → `~/.claude/memex/global/feedback/<slug>.md`")
    lines.append("- 项目专属纪律 → `~/.claude/memex/projects/<key>/feedback/<slug>.md`")
    lines.append("- 分支记忆 → `~/.claude/memex/projects/<key>/branches/<branch_slug>.md`")
    lines.append("- 写完 post-write-memory-sync hook 自动入索引")
    lines.append("")
    lines.append(CATALOG_END)
    return "\n".join(lines) + "\n"


def replace_or_append_bridge(memory_md: Path, bridge: str) -> str:
    """幂等替换/追加 memex:bridge 区块。返回 'created' / 'replaced' / 'appended' / 'unchanged'。"""
    if not memory_md.exists():
        memory_md.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(memory_md,
                          "<!-- Claude Code Auto Memory + Memex v0.2 bridge -->\n\n" + bridge)
        return "created"
    text = memory_md.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(BRIDGE_START) + r".*?" + re.escape(BRIDGE_END) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(text):
        new = pattern.sub(bridge, text)
        if new == text:
            return "unchanged"
        atomic_write_text(memory_md, new)
        return "replaced"
    new = text.rstrip() + "\n\n" + bridge
    atomic_write_text(memory_md, new)
    return "appended"


def ensure_memex_skeleton(memex: Path) -> bool:
    """memex 根 + global 骨架。返回是否首次建。"""
    bootstrap = not (memex / "_index").exists()
    for sub in ("_index", "global/feedback", "global/reference", "global/user", "projects"):
        (memex / sub).mkdir(parents=True, exist_ok=True)
    for f in ("projects.jsonl", "branches.jsonl", "meta.jsonl"):
        fpath = memex / "_index" / f
        if not fpath.exists():
            fpath.touch()
    gindex = memex / "global/INDEX.md"
    if not gindex.exists() and GLOBAL_TEMPLATE.exists():
        gindex.write_text(GLOBAL_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return bootstrap


def has_content(memex: Path, key: str) -> bool:
    """projects/<key>/ 下除 INDEX.md 外有任何 .md → True。"""
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


def recently_active_keys(memex: Path, days: int) -> set[str]:
    """从 projects.jsonl 找 last_access < N 天且有内容的 project keys。"""
    path = memex / "_index/projects.jsonl"
    if not path.exists():
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: set[str] = set()
    for r in load_jsonl(path):
        la = parse_iso(r.get("last_access", ""))
        if la and la >= cutoff:
            if has_content(memex, r["key"]):
                out.add(r["key"])
    return out


def touch_project(memex: Path, key: str, repo_path: Optional[str] = None) -> None:
    """--touch 模式:bump last_access for given project key in projects.jsonl。
    若 project 不在 jsonl 里,用 repo_path 派生信息建一条。
    """
    path = memex / "_index/projects.jsonl"
    rows = load_jsonl(path)
    existing = {r["key"]: r for r in rows if "key" in r}
    now = now_iso()
    if key in existing:
        rec = existing[key]
        rec["last_access"] = now
        if repo_path:
            paths = rec.get("repo_paths_seen", [])
            repo_abs = str(Path(repo_path).expanduser().resolve())
            if repo_abs not in paths:
                paths.append(repo_abs)
                rec["repo_paths_seen"] = paths
    elif repo_path:
        info = derive_for_repo(repo_path)
        if info and info.get("is_git") and info.get("key") == key:
            existing[key] = {
                "key": key,
                "display_name": info.get("display_name", key),
                "origin": info.get("origin", ""),
                "origin_aliases": info.get("origin_aliases", []),
                "repo_paths_seen": [info.get("repo_root", "")] if info.get("repo_root") else [],
                "tags": [],
                "first_seen": now,
                "last_access": now,
                "status": "active",
                "branch_count": 0,
            }
    else:
        # key 不存在且无 repo path → 无法新建,退出
        return
    rows_out = sorted(existing.values(), key=lambda r: r["key"])
    atomic_write_jsonl(path, rows_out)


def ensure_catalog_in_claude_md(memex: Path) -> str:
    """在 ~/.claude/CLAUDE.md 末尾幂等维护 <!-- memex:catalog --> 块。

    返回 'created' / 'replaced' / 'appended' / 'unchanged' / 'skipped'。

    Opt-out 两种(任一即跳过):
      · env MEMEX_NO_CATALOG=1
      · sentinel 文件 ~/.claude/memex/.no_catalog 存在(持久,不依赖 env)

    其它规则:
      · 文件不存在 → 创建最小 stub(只含 catalog 块)
      · 文件存在含 markers → 幂等替换(保持 markers 内容一致)
      · 文件存在不含 markers → 末尾追加

    用户永久 opt-out 的方法(文档明示):
      touch ~/.claude/memex/.no_catalog
    脚本不尝试"检测用户删了 markers"(不可靠 — 无法区分首次装 vs 删除)。
    """
    if os.environ.get("MEMEX_NO_CATALOG") == "1":
        return "skipped"
    sentinel = memex / ".no_catalog"
    if sentinel.exists():
        return "skipped"

    # v0.2.2:catalog 从「@import 全 INDEX」改成「极简 manifest」直接写入
    catalog = build_catalog_manifest(memex)

    if not USER_CLAUDE_MD.exists():
        USER_CLAUDE_MD.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(USER_CLAUDE_MD,
                          "<!-- ~/.claude/CLAUDE.md — 用户级 Claude 规则 + Memex catalog -->\n\n" + catalog)
        return "created"

    text = USER_CLAUDE_MD.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(CATALOG_START) + r".*?" + re.escape(CATALOG_END) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(text):
        new = pattern.sub(catalog, text)
        if new == text:
            return "unchanged"
        atomic_write_text(USER_CLAUDE_MD, new)
        return "replaced"
    new = text.rstrip() + "\n\n" + catalog
    atomic_write_text(USER_CLAUDE_MD, new)
    return "appended"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cwd", help="(主模式)cwd 路径,扫子目录所有 git repo")
    parser.add_argument("--memex", default=str(DEFAULT_MEMEX))
    parser.add_argument("--cc-memory", help="Claude Code per-cwd MEMORY.md path(默认按 cwd 派生)")
    parser.add_argument("--touch", metavar="KEY", help="touch 模式:bump 该 project_key 的 last_access")
    parser.add_argument("--repo", help="touch 模式 + 新 project 时用:repo path")
    args = parser.parse_args()

    memex = Path(args.memex).expanduser()

    # --touch 模式:快速 bump,不动 bridge / catalog
    if args.touch:
        ensure_memex_skeleton(memex)
        touch_project(memex, args.touch, args.repo)
        print(json.dumps({"touched": args.touch}, ensure_ascii=False))
        return 0

    # 主模式:要求 --cwd
    if not args.cwd:
        print("✗ 主模式需要 --cwd", file=sys.stderr)
        return 2

    # cwd_raw 不解 symlink(跟 Claude Code 自己的 cwd-slug 算法一致 — CC 用 raw pwd)
    # cwd_for_scan 解 symlink(扫子目录 git repo 需要绝对路径)
    cwd_raw = Path(args.cwd).expanduser()
    cwd_for_scan = cwd_raw.resolve()
    bootstrap = ensure_memex_skeleton(memex)

    repos = discover_repos(cwd_for_scan)
    new_count = 0
    for info in repos:
        if ensure_project_skeleton(memex, info):
            new_count += 1
    upserted = upsert_projects_jsonl(memex, repos)

    # cwd-发现的有内容项目
    cwd_active = {r["key"] for r in repos if has_content(memex, r["key"])}
    # recently active(任何用户最近碰过的有内容项目)
    recent_active = recently_active_keys(memex, RECENT_DAYS)
    # 合并
    active_keys = sorted(cwd_active | recent_active)

    bridge = build_bridge_block(memex, active_keys)

    # 默认 MEMORY.md 路径(用 raw cwd 算 slug,跟 Claude Code 对齐)
    if args.cc_memory:
        cc_memory = Path(args.cc_memory).expanduser()
    else:
        cwd_slug = str(cwd_raw).replace("/", "-")
        cc_memory = HOME / ".claude/projects" / cwd_slug / "memory/MEMORY.md"

    bridge_action = replace_or_append_bridge(cc_memory, bridge)
    catalog_action = ensure_catalog_in_claude_md(memex)

    result = {
        "bootstrap": bootstrap,
        "new_projects": upserted,
        "discovered_repos": len(repos),
        "cwd_active_keys": sorted(cwd_active),
        "recent_active_keys": sorted(recent_active - cwd_active),
        "active_imported_keys": active_keys,
        "memory_md": str(cc_memory),
        "bridge_action": bridge_action,
        "catalog_action": catalog_action,
        "catalog_path": str(USER_CLAUDE_MD),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
