#!/usr/bin/env python3
"""
derive_project_key.py — Memex v0.2 项目身份派生

把一个 git repo 路径派生成 (project_key, display_name, origin, origin_aliases)。
所有 hook 和 Python 工具调它,不自己实现。

Usage:
    derive_project_key.py <repo_path>           # 单 repo,出 JSON
    derive_project_key.py --scan <parent_dir>   # 扫描 parent 下所有 git repo,出 JSONL
    derive_project_key.py --normalize <url>     # 只跑 URL 归一化(测试用)

Output(单 repo,JSON):
{
  "repo_root": "/Users/you/code/example-service",
  "is_git": true,
  "origin": "github.com/example-org/example-service",
  "origin_aliases": ["git@github.com:example-org/example-service.git"],
  "key": "a1b2c3d4e5f6-example-service",
  "display_name": "example-service",
  "key_source": "origin"  # or "abspath"
}

无 origin → key 由 abspath hash 派生。
非 git repo → is_git=false,无 key。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# ── URL 归一化 ──────────────────────────────────────────────────────

_PROTOCOL_RE = re.compile(
    r"^(?:"
    r"git@([^:]+):(.+)"        # SSH:  git@host:path
    r"|ssh://(?:git@)?([^/]+)/(.+)"  # SSH-URL: ssh://[git@]host/path
    r"|https?://(?:[^@]+@)?([^/]+)/(.+)"  # HTTP(S): https://[user@]host/path
    r"|git://([^/]+)/(.+)"     # git://host/path
    r")$"
)


def normalize_origin(url: str) -> str:
    """
    git@github.com:org/repo.git
    https://github.com/org/repo.git/
    ssh://git@github.com/org/repo
            ↓
    github.com/org/repo
    """
    if not url:
        return ""
    url = url.strip().rstrip("/")

    m = _PROTOCOL_RE.match(url)
    if m:
        groups = [g for g in m.groups() if g is not None]
        if len(groups) >= 2:
            host, path = groups[0], groups[1]
        else:
            return url.lower()
    else:
        # 不认得的格式,原样小写返回
        return url.lower()

    # strip .git 后缀和尾斜杠
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]

    return f"{host.lower()}/{path}"


# ── key 派生 ──────────────────────────────────────────────────────

def safe_basename(name: str) -> str:
    """文件名安全的 basename,去掉非 [a-zA-Z0-9_-]"""
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-") or "unnamed"


def derive_key(origin_normalized: str, repo_root: str) -> tuple[str, str]:
    """
    返回 (key, source)。
    source ∈ {"origin", "abspath"}。
    """
    basename = safe_basename(Path(repo_root).name)
    if origin_normalized:
        h = hashlib.sha1(origin_normalized.encode("utf-8")).hexdigest()[:12]
        return f"{h}-{basename}", "origin"
    else:
        abspath = str(Path(repo_root).resolve())
        h = hashlib.sha1(abspath.encode("utf-8")).hexdigest()[:12]
        return f"{h}-{basename}", "abspath"


# ── git 探测 ──────────────────────────────────────────────────────

def _git(repo: str, *args: str) -> str | None:
    try:
        res = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def get_repo_root(path: str) -> str | None:
    return _git(path, "rev-parse", "--show-toplevel")


def get_all_origins(repo: str) -> list[str]:
    """
    拿 origin 远程的所有 URL(可能有多个 push/fetch URL)。
    优先 origin;没有 origin 拿第一个 remote。
    """
    remotes = _git(repo, "remote") or ""
    remote_list = [r for r in remotes.splitlines() if r]
    if not remote_list:
        return []
    target = "origin" if "origin" in remote_list else remote_list[0]
    urls: list[str] = []
    # 拿主 URL
    u = _git(repo, "remote", "get-url", target)
    if u:
        urls.append(u)
    # 拿所有 URL(可能有多个,git remote get-url --all)
    all_u = _git(repo, "remote", "get-url", "--all", target)
    if all_u:
        for line in all_u.splitlines():
            if line and line not in urls:
                urls.append(line)
    return urls


# ── 主入口 ─────────────────────────────────────────────────────────

def derive(path: str) -> dict:
    abs_path = str(Path(path).expanduser().resolve())
    repo_root = get_repo_root(abs_path)
    if not repo_root:
        return {
            "input_path": abs_path,
            "is_git": False,
            "key": None,
            "display_name": None,
            "origin": "",
            "origin_aliases": [],
            "repo_root": None,
            "key_source": None,
        }

    urls = get_all_origins(repo_root)
    if urls:
        primary = urls[0]
        normalized = normalize_origin(primary)
        aliases = [u for u in urls if u != primary]
    else:
        primary = ""
        normalized = ""
        aliases = []

    key, source = derive_key(normalized, repo_root)

    return {
        "repo_root": repo_root,
        "is_git": True,
        "origin": normalized,
        "origin_primary_url": primary,
        "origin_aliases": aliases,
        "key": key,
        "display_name": Path(repo_root).name,
        "key_source": source,
    }


def scan_parent(parent: str) -> list[dict]:
    """扫描 parent 下所有 .git(深度 ≤ 4)。"""
    parent_p = Path(parent).expanduser().resolve()
    if not parent_p.is_dir():
        return []
    found: list[dict] = []
    seen_roots: set[str] = set()
    # 深度优先,只看 .git 目录(submodule 也会有 .git 文件,跳)
    for git_path in parent_p.glob("**/.git"):
        # 限制深度 ≤ 4(parent + 3 levels)
        depth = len(git_path.relative_to(parent_p).parts)
        if depth > 4:
            continue
        repo_root = str(git_path.parent.resolve())
        if repo_root in seen_roots:
            continue
        seen_roots.add(repo_root)
        info = derive(repo_root)
        if info["is_git"]:
            found.append(info)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", nargs="?", help="repo path to derive (default: cwd)")
    parser.add_argument("--scan", metavar="PARENT", help="scan PARENT for all git repos")
    parser.add_argument("--normalize", metavar="URL", help="only normalize a URL (test mode)")
    parser.add_argument("--table", action="store_true", help="output as aligned table instead of JSON")
    args = parser.parse_args()

    if args.normalize:
        print(normalize_origin(args.normalize))
        return 0

    if args.scan:
        results = scan_parent(args.scan)
        if args.table:
            if not results:
                print("(no git repos found)")
                return 0
            w_name = max(len(r["display_name"]) for r in results)
            w_origin = max(len(r["origin"]) for r in results)
            print(f"{'display_name':<{w_name}} | {'origin':<{w_origin}} | key")
            print("-" * (w_name + w_origin + 30))
            for r in results:
                print(f"{r['display_name']:<{w_name}} | {r['origin']:<{w_origin}} | {r['key']}")
        else:
            for r in results:
                print(json.dumps(r, ensure_ascii=False))
        return 0

    target = args.path or os.getcwd()
    result = derive(target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["is_git"] else 1


if __name__ == "__main__":
    sys.exit(main())
