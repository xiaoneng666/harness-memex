# Changelog

## v0.2.2 (2026-06-03) — 按需查询取代全量 @import

### Why

v0.2.1 用 `~/.claude/CLAUDE.md` catalog 块 `@import` 全局 INDEX,bridge 块 `@import` 每个 active project 的 INDEX — 35 个 active project 时 ctx 占用 ~30KB。两个问题:

1. **强依赖 Claude 原生 memory**:MEMORY.md bridge 在 `/compact` 后可能丢(MEMORY.md 不在 CC 原生 re-inject 名单)
2. **预载内容而非索引**:违反 spec § 七「索引非内容,按需注入」原则 — INDEX.md 被 Claude Code 全文展开进 ctx

### What changed

**New CLI: `bin/memex_query.py`** — 7 个子命令,LLM 按需用 Bash 主动查:

```
--list                       # 列所有 active project
--project <key>              # 看 project 元数据 + 分支 + feedback + reference
--branch <key> <slug>        # 拿分支 memory 路径
--feedback [--project-filter KEY] [--term TERM]
--reference [--project-filter KEY] [--term TERM]
--grep <term>                # 跨索引模糊查
--recent [--days N]          # 最近 access 过的
--health                     # 索引完整性自检
```

支持 `--json` 给脚本管道用。失败 exit 非 0 + stderr,LLM 看得到。

**Catalog → 极简 manifest(不再 @import)**:

`~/.claude/CLAUDE.md` 的 catalog 块从「@import global INDEX」改成直接写入项目目录:
- 项目列表(key + display + origin + branch_count)
- 7 个 query CLI 用法
- 写新 memory 的路径约定

实际尺寸:**~2KB**(对比 v0.2.1 的 ~7KB+ + 各 project INDEX 全展开)。

**Bridge 降级为指示性注释**:

`MEMORY.md` 的 bridge 块不再 @import,只剩 4 行注释告诉 LLM「catalog 在 CLAUDE.md,查询用 memex_query.py」。**~400 字节**。

**Hook ctx 加 query 教学**:

`post-checkout-handoff.sh` / `pre-edit-branch-notice.sh` ctx 末尾加一段「想看更多 → `memex_query.py --project KEY` / `--feedback --project-filter KEY` / `--grep TERM`」。LLM 在触发时既得到具体路径(push),也学会按需查询(pull)。

### 体现的原则

| 原则 | v0.2.1 | v0.2.2 |
|---|---|---|
| **索引非内容,按需注入** | catalog @import 全 INDEX 进 ctx | catalog 内联极简 manifest,内容靠 query CLI 按需拉 |
| **不强依赖 Claude 原生 memory** | bridge 在 MEMORY.md /compact 后丢 | catalog 在 CLAUDE.md(survive compact);bridge 仅指示性 |
| **脚本塞事实,LLM 决策** | hook ctx 给路径 | hook ctx 给路径 + 教 LLM 用 query CLI 按需拉 |
| **失败兜底闭环** | 不变 | memex_query.py 失败 exit 非 0 + stderr |

### 升级

`./install.sh` 重跑会复制新的 `bin/memex_query.py`,下次 session bootstrap 自动重写 catalog 成 manifest 格式。无需手动迁移。

旧的 `@import` 链不删也无害(`@global/INDEX.md` 还在),但新机制下基线 ctx 降到 ~2KB。

---

## v0.2.1 (2026-06-03) — 项目共享层彻底解耦 cwd

把 v0.2 还残留的「project 共享层(INDEX / overview / 项目 feedback / reference)只在 cwd subtree 扫到时自动加载」缺口填上。

### Why

v0.2 数据层和分支层都跟 cwd 无关,但**项目共享层**(`projects/<key>/INDEX.md` 及里面链接的 overview / 项目专属 feedback / reference)还依赖 bootstrap 的 cwd subtree 扫描。如果用户在 `/tmp` 启动 Claude → `cd ~/anywhere/project-X` 干活,X 的分支记忆能通过 hook 拉到,但 X 的项目共享层不会自动进 ctx。

v0.2.1 用两个互补机制彻底解耦:

### B — 触发式同会话 hook ctx 增强

- `post-checkout-handoff.sh`:切分支时 ctx 多加一条「Read project INDEX」,把项目共享层 + 分支层一回合并行拉齐
- `pre-edit-branch-notice.sh`:编辑时 ctx 同样含「Read project INDEX」+「Read 分支 memory」两份
- 两个 hook 后台异步跑 `update_memex_bridge.py --touch <key> --repo <path>`,更新 `projects.jsonl.last_access`,让下次 session bootstrap 把 project 加进 bridge

### C — `~/.claude/CLAUDE.md` 全局 catalog @import

- `update_memex_bridge.py` 主模式在 `~/.claude/CLAUDE.md` 末尾幂等维护 `<!-- memex:catalog -->` 块,内容是 `@~/.claude/memex/global/INDEX.md`
- Claude Code 原生加载 `~/.claude/CLAUDE.md`(用户级) → 全局 INDEX 在**任何 cwd / 任何 session** 都自动进 ctx
- 全局 INDEX 列所有 project + 一句话简介,LLM 始终知道哪个 project 在哪
- 永久 opt-out 两种(任一即跳过):
  - `touch ~/.claude/memex/.no_catalog`(sentinel 文件,持久且不依赖 shell env)
  - `export MEMEX_NO_CATALOG=1`(shell env,适合临时 / 跨工具)
- 文件不存在 → 自动创建最小 stub

### Bridge 增强

`update_memex_bridge.py` 主模式的 bridge 包含范围扩了:
- cwd-discovered 项目中有内容的(原 v0.2 行为)
- + `projects.jsonl.last_access < 30d`(可配 `MEMEX_RECENT_DAYS`)且有内容的(v0.2.1 新增)

意味着:一旦用户在任何 cwd 触发过 post-checkout / pre-edit,该 project 30d 内任何 session 启动都自动 @import 它的 INDEX。

### 新增 / 改

- `bin/update_memex_bridge.py`:加 `--touch <key> [--repo <path>]` 模式 + recently-active 合并 + catalog 维护
- `hooks/post-checkout-handoff.sh`:ctx 多加 project INDEX 行 + 后台 --touch
- `hooks/pre-edit-branch-notice.sh`:ctx 多加 project INDEX 行 + 后台 --touch

### 用户体验对比

| 场景 | v0.2 | v0.2.1 |
|---|---|---|
| 在不相关 cwd 启动 Claude(如 `/tmp`)| 只 global INDEX 进 ctx,项目级 docs 不在 | global catalog + recently-active 项目 INDEX 都自动 @import |
| 切到 project X 的 branch | 只 branch memory 注入 ctx | branch memory + project INDEX **同回合并行** Read |
| 编辑 project X 的文件 | 只分支 memory 提示 | branch memory + project INDEX 同时提示 |
| 触发后下次 session | project 不在 bridge | project 进 recently-active → bridge 自动 @import |

---

## v0.2 (2026-06-03) — 项目维度全局池

**架构重写:从「每 cwd 独立 mem_root」转向「Claude 原生 + memex 项目维度扩展」**。

### Motivation

v0.1 的「每 cwd 独立 mem_root」在「workspace 父 cwd + N 个 git 子项目」工作流下退化成单池:
- 主 cwd 启动 Claude,然后 `cd` 到子项目跑命令 → 所有子项目共用一份 cwd 池,记忆混在一起
- worktree 因 [Claude Code issue #39920](https://github.com/anthropics/claude-code/issues/39920)(用 `git-common-dir` 派生 slug)也共用主 worktree 的池,串

v0.2 改成 **按 git origin 派生 project-key** 隔离 — 跟 cwd 无关、跟 worktree 无关、跟启动位置无关。

### Breaking Changes

- **目录结构换地方**:`~/.claude/projects/<cwd-slug>/memory/projects/<biz>/...` → `~/.claude/memex/projects/<project-key>/...`
- **JSONL schema 变**:`by_branch.jsonl` 改名 `branches.jsonl`,schema 加 `project_key` / `branch_slug` / `memory_path` 字段
- **INDEX 模板从 1 个变 2 个**:`INDEX_TEMPLATE.md` 弃用,改 `MEMEX_GLOBAL_INDEX_TEMPLATE.md` + `MEMEX_PROJECT_INDEX_TEMPLATE.md`
- **CLAUDE 原生 `MEMORY.md` 不再被改写为软链**,而是末尾幂等追加 `<!-- memex:bridge -->` 区块

### New

- `bin/derive_project_key.py` — git origin 归一化 + sha1[:12] 派生 project-key,所有 hook 单一依赖
- `bin/update_memex_bridge.py` — 扫 cwd 子目录所有 git repo,确保 memex 骨架 + 在 Claude `MEMORY.md` 末尾注入 `@import` 桥
- `bin/migrate_v01_to_v02.py` — YAML mapping 驱动的一次性迁移(dry-run + backup + copy + 旧池不删等 LRU 回收)
- `templates/MEMEX_GLOBAL_INDEX_TEMPLATE.md` + `templates/MEMEX_PROJECT_INDEX_TEMPLATE.md`
- `examples/migrate-mapping.example.yaml` — 迁移配置示例

### Changed

- `MEMORY_SPEC.md` — 全面重写,加 § 十「project-key 隔离矩阵」,§ 九 标记 deprecate
- `hooks/session-bootstrap.sh` — 薄壳,业务逻辑全在 `update_memex_bridge.py`(修 bash 3.x `declare -A` 不兼容、十六进制 key 误算术、awk 多行字符串等 bug)
- `hooks/post-checkout-handoff.sh` — 改用 `derive_project_key` + `branches.jsonl` O(1) 查找
- `hooks/pre-edit-branch-notice.sh` — 同上
- `hooks/post-write-memory-sync.sh` — 路径监控从 `~/.claude/projects/*/memory/` 改到 `~/.claude/memex/`
- `hooks/pre-read-memory-bump.sh` — 路径监控同上
- `hooks/session-start-lru.sh` — 默认 LRU 目标改成 memex 根
- `bin/rebuild_index.py` — 扫 memex 重建 3 个 jsonl(meta + branches + projects)
- `bin/update_index_md.py` — 渲染 global/INDEX.md + 每 project 的 INDEX.md(用 AUTO 标记区块)
- `bin/lru_compact.py` — 默认 root 改 `~/.claude/memex`;`--detect-deleted-branches` 改按 project_key 对账

### 升级路径(从 v0.1)

```bash
# 1. 拉新代码,重装
git pull && ./install.sh

# 2. 写迁移 mapping(见 examples/migrate-mapping.example.yaml)
cp examples/migrate-mapping.example.yaml ~/my-mapping.yaml
$EDITOR ~/my-mapping.yaml

# 3. dry-run 看 plan
python3 ~/.claude/bin/migrate_v01_to_v02.py \
  --source ~/.claude/projects/<your-old-cwd-slug>/memory \
  --mapping ~/my-mapping.yaml

# 4. 满意了就 --apply
python3 ~/.claude/bin/migrate_v01_to_v02.py \
  --source ~/.claude/projects/<your-old-cwd-slug>/memory \
  --mapping ~/my-mapping.yaml \
  --apply

# 5. 旧池保留(LRU 30d × 3 次压缩后自然回收;急可手动 rm)
```

### Bridge 优化:只 @import 有内容的项目

bootstrap 扫 cwd 下所有 git repo,但 `MEMORY.md` 的 bridge 只 @import 「projects/<key>/ 下除 INDEX.md 外有 .md」的项目,避免数十个空 stub 塞 ctx。
新 project 一旦写入第一个 memory 文件,下次 session 自动进 bridge。

---

## v0.1 — 初始发布

参见早期 README / docs。
