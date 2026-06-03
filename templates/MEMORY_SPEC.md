# Memory 系统 — 全局规范(v0.2)

> 任何 cwd / 任何 Claude 进程都遵守。
> v0.2 转向「Claude Code 原生 + memex 项目维度扩展」双层架构;v0.1 的「每 cwd 独立 mem_root」已 deprecate(详见 § 九)。

---

## 〇、架构总览

```
Claude Code 原生(我们不动一行)
├── ~/.claude/CLAUDE.md                          ← 用户级 rules
├── ~/.claude/rules/                              ← 用户级 rules 目录
└── ~/.claude/projects/<cc-slug>/memory/         ← Auto Memory(per repo,共享 worktree)
    └── MEMORY.md                                  ← Claude 读写,首 200 行 / 25KB 注入 ctx
        ↓ memex bootstrap 在末尾幂等追加(<!-- memex:bridge --> 区块):
        # @~/.claude/memex/global/INDEX.md
        # @~/.claude/memex/projects/<key-A>/INDEX.md
        # @~/.claude/memex/projects/<key-B>/INDEX.md

Memex 全局池(项目维度,无 cwd 维度)
~/.claude/memex/
├── _index/                                       ← harness 关键(JSONL O(1) 查)
│   ├── projects.jsonl                            project-key → 元数据
│   ├── branches.jsonl                            (project-key, branch) → memory_path
│   └── meta.jsonl                                LRU + decay(所有 memex .md)
├── global/                                       ← 机器全局(跨项目)
│   ├── INDEX.md
│   ├── feedback/                                 跨项目纪律
│   ├── reference/                                跨项目外部引用
│   └── *.md                                      跨项目集合文档
└── projects/
    └── <project-key>/                            一个 git repo = 一个 key,**压平**
        ├── INDEX.md                              项目门面(被 Claude MEMORY.md @import)
        ├── overview.md                           长期决策
        ├── feedback/                             项目专属纪律
        ├── reference/                            项目专属外部引用
        ├── *.md                                  长期决策
        └── branches/
            └── <branch-slug>.md                  ← 分支记忆只此一份
```

---

## 一、目录结构(双层池)

### 1.1 Claude Code 原生层(`~/.claude/projects/<cc-slug>/memory/`)

由 Claude Code v2.1.59+ 自己维护。我们**只在 `MEMORY.md` 末尾幂等追加 `@import` 行**,其它不动。

- `<cc-slug>` 由 Claude Code 内部 `git rev-parse --git-common-dir` 派生(per-repo,worktree 共享 — 见官方 [memory docs](https://code.claude.com/docs/en/memory))
- 不在 git repo 内 → 用 cwd 路径
- `MEMORY.md` 首 200 行 / 25KB 自动注入 every session

### 1.2 Memex 全局池(`~/.claude/memex/`)

```
memex/
├── _index/                                      § 二 详述
├── global/INDEX.md                              所有 cwd 都 @import 它
├── global/feedback/<slug>.md
├── global/reference/<slug>.md
├── global/*.md
└── projects/<project-key>/                      § 三 详述 project-key 派生
    ├── INDEX.md                                 该项目门面
    ├── overview.md
    ├── feedback/<slug>.md
    ├── reference/<slug>.md
    ├── *.md
    └── branches/<branch_slug>.md
```

**slug 规范**:`/` 和 `-` 替换成 `_`(如 `feat/0531/example-feature` → `feat_0531_example_feature`)。

---

## 二、JSONL 索引 schema(harness 关键)

为支持 hook 的 O(1) 查找而设计,**三套 jsonl 各管一事**。

### 2.1 `_index/projects.jsonl`(每项目一行)

```json
{
  "key": "a1b2c3d4e5f6-example-service",
  "display_name": "example-service",
  "origin": "github.com/example-org/example-service",
  "origin_aliases": ["git@github.com:example-org/example-service.git"],
  "repo_paths_seen": ["/Users/you/code/example-service"],
  "tags": ["backend"],
  "first_seen": "2026-06-01T00:00:00Z",
  "last_access": "2026-06-03T16:00:00Z",
  "status": "active",
  "branch_count": 4
}
```

### 2.2 `_index/branches.jsonl`(每分支记忆一行)

```json
{
  "project_key": "a1b2c3d4e5f6-example-service",
  "branch": "feat/0531/example-feature",
  "branch_slug": "feat_0531_example_feature",
  "memory_path": "projects/a1b2c3d4e5f6-example-service/branches/feat_0531_example_feature.md",
  "status": "active",
  "last_access": "2026-06-01T10:00:00Z",
  "decay": 0,
  "size": 4521,
  "alive_on_remote": true,
  "alive_locally": true
}
```

### 2.3 `_index/meta.jsonl`(全部 memex 文件,LRU 用)

```json
{
  "path": "projects/<key>/branches/<slug>.md",
  "type": "branch|overview|feedback|reference|global|user",
  "project_key": "<key>",
  "branch": "<branch>",
  "name": "<kebab-slug>",
  "description": "<一句话>",
  "status": "active|dormant|pinned|candidate_to_delete",
  "last_access": "...",
  "decay": 0,
  "size": 4521
}
```

`type` ∈ {`branch`, `overview`, `feedback`, `reference`, `global`, `user`}。
`project_key` / `branch` 字段对 global/user 类为 `""`。

### 2.4 热路径查询样板

```bash
MEMEX="$HOME/.claude/memex"

# ① 切分支:project_key + branch → memory 文件(O(1))
jq -r --arg k "$key" --arg b "$branch" \
  'select(.project_key==$k and .branch==$b) | .memory_path' \
  "$MEMEX/_index/branches.jsonl" | head -1

# ② LRU 扫:30d+ dormant 候选
jq -c --arg cutoff "$cutoff" \
  'select(.status=="active" and .last_access < $cutoff)' \
  "$MEMEX/_index/meta.jsonl"

# ③ 分支死亡:branches.jsonl × git for-each-ref 对账
```

---

## 三、project-key 派生(确定性、跨机器稳定)

由 `~/.claude/bin/derive_project_key.py <repo_path>` 输出。所有 hook 都调它,不自己实现。

```
有 origin:    sha1(normalize(origin))[:12] + "-" + basename(repo_root)
无 origin:    sha1(abspath(repo_root))[:12]  + "-" + basename(repo_root)
非 git repo:  无 key,不进 memex(只走 Claude 原生 MEMORY.md)
```

**normalize 规则**:
```
git@github.com:org/repo.git
https://github.com/org/repo.git/
ssh://git@github.com/org/repo
            ↓ 全部归一成
github.com/org/repo
```

**好处**:
- 绕过 [issue #39920](https://github.com/anthropics/claude-code/issues/39920)(`git rev-parse --git-common-dir` 在 worktree 返主 worktree 的 bug)
- Worktree 同 key + 不同 branch = 不同 memory 文件
- SSH↔HTTPS 切换 → 归一化后同 key,不漂

**origin 迁移记录**:在 `projects.jsonl.origin_aliases` 数组里追加历史值,key 变了走 alias 反查。

---

## 四、LRU 淘汰策略(状态机,30d 周期 × 3 次压缩)

| `status` | `decay` | 何时进 | LRU 工具行为 |
|---|---|---|---|
| `active` | 0 | 默认起始 | 不动 |
| `active` | 0 | `last_access ≥ 30d` | `pending_compact_1` → LLM 压缩 → 写回 `dormant decay=1` |
| `dormant` | 1 | 又 30d 未 access | `pending_compact_2` → 压缩到 `decay=2` |
| `dormant` | 2 | 又 30d 未 access | `pending_compact_3` → 压缩到 `decay=3` |
| `dormant` | 3 | 又 30d 未 access | `pending_delete` → `status=candidate_to_delete`,**通知用户** |
| `candidate_to_delete` | 3 | **用户授权** | `rm` + 从 jsonl 移除 |
| `pinned` | - | **用户显式锁** | 永不淘汰 |

**关键约束**:
- 压缩内容**由 LLM 做**(理解上下文后写出紧凑版),工具只列候选 + 改 decay/status
- **删除前必须用户授权**(`candidate_to_delete` 状态)
- `last_access` 由 hook 自动维护,**LLM 不要手动改**
- 周期可配:`export MEMEX_LRU_PERIOD_DAYS=30`
- 显式锁定:`python3 ~/.claude/bin/lru_compact.py --pin <rel_path>` / 解锁 `--unpin`

### 4.1 压缩 SOP

工具 `~/.claude/bin/lru_compact.py` 扫到候选后输出清单。LLM:
1. **逐条 Read 全文**(可并行)
2. **按 decay 级别写紧凑版**,Write 覆盖:
   - decay 0→1:frontmatter + Why / 关键决策 / 当前状态 + 链接,size ≤ 2KB
   - decay 1→2:frontmatter + 1-2 段核心 + 链接,size ≤ 800B
   - decay 2→3:frontmatter + 1-3 句精华 + 链接,size ≤ 300B
3. **写完后跑** `lru_compact.py --mark <rel_path> <new_decay>` 更新 jsonl

### 4.2 分支死亡 → 进 LRU

工具 `lru_compact.py --detect-deleted-branches <project_key> <repo_path>`:
- 用 `git for-each-ref refs/heads refs/remotes` 拿存活分支
- 跟 `branches.jsonl` 中该 project_key 的条目对账
- **本地远程都查不到** → `status=dormant`(并入下一周期 LRU)

---

## 五、写 memory 的纪律(harness 风格)

只记**主要的**,不堆细节:

| 该记 | 不该记 |
|---|---|
| ✅ 改动(高层 — 哪些文件,做了什么改造) | ❌ 每行 diff |
| ✅ 状态(已部署 / 已 merge / 待修 / 已废弃)| ❌ commit hash 全清单 |
| ✅ 思路(Why / 架构决策 / 踩坑教训) | ❌ 详细技术叙述 |
| ✅ 进度(完成度 / 阻塞点 / 下一步) | ❌ 时间日志 |

frontmatter 固定:
```yaml
---
name: <kebab-case-slug>
description: <一句话摘要,索引里展示用>
metadata:
  type: feedback|reference|user|project|branch|global|overview
  project_key: <key>          # branch / project-scoped 类必填
  branch: <branch>            # 仅 branch 类必填
---
```

**新加 memory 后自动入索引**:Write/Edit 到 `~/.claude/memex/**/*.md` → `post-write-memory-sync.sh` 自动增量同步进 3 个 jsonl。

---

## 六、Hook 行为(全局生效)

| Hook | 触发 | 动作 |
|---|---|---|
| `session-bootstrap.sh` | PreToolUse * | 调 `update_memex_bridge.py`:扫 cwd 子目录所有 git repo,确保 memex 骨架,upsert projects.jsonl,在 `<cc-slug>/memory/MEMORY.md` 末尾幂等替换 `<!-- memex:bridge -->` 区块,内容是 `@global/INDEX.md` + 有内容项目的 `@projects/<key>/INDEX.md` |
| `pre-read-memory-bump.sh` | PreToolUse Read | Read `~/.claude/memex/**/*.md` → 更新 `_index/meta.jsonl.last_access` |
| `check-protected-branch.sh` | PreToolUse Bash | git commit/push 到保护分支拦截(不变) |
| `pre-edit-branch-notice.sh` | PreToolUse Edit/Write | 编辑前 derive_project_key + 查 branches.jsonl,提示当前 (project_key, branch) memory 路径 |
| `post-checkout-handoff.sh` | PostToolUse Bash | git checkout/switch 成功后,塞 ctx 让 LLM 并行 Write from_branch + Read to_branch,路径来自 branches.jsonl(O(1) 查) |
| `post-write-memory-sync.sh` | PostToolUse Write/Edit | 文件路径在 `~/.claude/memex/**/*.md` → 自动增量入 3 个 jsonl |
| `session-start-lru.sh` | SessionStart | 跑 `lru_compact.py --quiet`,有候选塞 ctx 让 LLM 自决策压缩 |

**Hook 工程纪律**(不变):
- 失败永远 `exit 0`(除保护分支拦截 exit 2)
- 错误输出到 stderr **同时** 通过 `hookSpecificOutput.additionalContext` 抛给 LLM
- 写 jsonl 必须 tmpfile + mv(原子)
- 同 session 同 cwd 同分支去重(`/tmp/memex-*-marker`)
- 索引坏掉 → fallback 到 `ls memex/projects/*/branches/<slug>.md` 全盘 glob
- **hook 不解析复杂 shell** — 只支持 `cd <path>` / `git -C <path>` 两种最简形式,其它一律 ⚠️ 兜底 ctx

---

## 七、Bootstrap(新 cwd / 新 project 自动适配)

逻辑(幂等状态机,实现在 `~/.claude/bin/update_memex_bridge.py`):

1. `MEMEX=~/.claude/memex`
2. 若 `MEMEX` 不存在 → 建骨架(`_index/`、`global/`、`projects/`、3 个 jsonl)
3. 扫 `pwd` 子目录(深度 ≤ 4)所有 `.git` → 拿 `repo_root` 列表
4. 对每个 `repo_root`:
   - 调 `derive_project_key.py` 拿 `key` + `display_name` + `origin`
   - 若 `MEMEX/projects/<key>/` 不存在 → 建骨架 + 从 `MEMEX_PROJECT_INDEX_TEMPLATE.md` 复制 INDEX.md
   - 在 `projects.jsonl` upsert 一条
5. 算 `cc_slug = $(pwd | sed 's#/#-#g')` 兜底
6. 在 `~/.claude/projects/<cc_slug>/memory/MEMORY.md` 末尾幂等追加/替换 `<!-- memex:bridge -->` 区块。**@import 范围**(v0.2.1):
   - `global/INDEX.md`(永远)
   - cwd-discovered 有内容的 project(v0.2 行为)
   - `projects.jsonl.last_access < MEMEX_RECENT_DAYS`(默认 30d)且有内容的 project(v0.2.1 新增)— **任何 cwd 启动都能看到最近碰过的项目**
7. 在 `~/.claude/CLAUDE.md` 末尾幂等维护 `<!-- memex:catalog -->` 区块,内容**极简 manifest**(v0.2.2,~2KB):
   - 项目目录(key + display + origin + branch_count)
   - `memex_query.py` 7 子命令用法
   - 写新 memory 的路径约定
   - **不再 @import 全 INDEX**(v0.2.1 行为已 deprecate — 旧做法在 35 active 项目时占 ~30KB ctx 且违反 spec § 七「索引非内容,按需注入」)
   - 永久 opt-out 两种(任一即跳过):
     - `touch ~/.claude/memex/.no_catalog`(sentinel,持久)
     - `export MEMEX_NO_CATALOG=1`(shell env)
   - 文件不存在 → 创建最小 stub
8. `MEMORY.md` 的 `<!-- memex:bridge -->` 区块降级为**指示性注释**(v0.2.2,~400 字节):
   - 4 行注释告诉 LLM「catalog 在 CLAUDE.md;查询用 `memex_query.py`」
   - **不再 @import 任何 INDEX**(v0.2.1 的「@global INDEX + @每个 project INDEX」已 deprecate)
   - 避免 MEMORY.md 在 `/compact` 后丢 bridge 的脆弱依赖

## 七.A、触发式 ctx 与 lazy bridge(v0.2.1)

`post-checkout-handoff.sh` / `pre-edit-branch-notice.sh` 在 hook 命中时:

- **同会话 ctx**:除塞「分支 memory 路径」外,还塞「project INDEX 路径」让 LLM 同回合并行 Read,把项目共享层 + 分支层一次拉齐
- **跨会话 lazy**:后台异步跑 `update_memex_bridge.py --touch <key> --repo <path>`,bump `projects.jsonl.last_access` → 该 project 进 recently-active → 下次 session bootstrap 自动 @import

效果:用户在任何 cwd 一旦触发过该 project,30d 内**所有 session**(任何 cwd / 任何 Claude 进程)都能自动拿到该 project 的共享层。

---

## 八、Harness 工程原则

| 原则 | 在 v0.2 的体现 |
|---|---|
| **单一职责** | 每个 hook 做一件事 |
| **幂等** | bootstrap 检测存在跳过;jsonl 用 tmpfile+mv;`memex:bridge` 区块按标记重写 |
| **零状态/确定性** | 索引完全由 `.md` + repo origin 推导;重建始终得同样结果 |
| **可观测** | hook 错误到 stderr,LLM 看得到 |
| **可降级** | jsonl 坏 → fallback glob;jq 缺 → grep;Python 缺 → hook 退化为提示 |
| **可演进** | jsonl 加字段不破老查 |
| **可回滚** | v0.1 旧池保留(等 LRU 回收);v0.2 全部进 `~/.claude/memex/`,删该目录即回退 |
| **隔离** | project-key 维度,跨 cwd 跨 worktree 一致 |
| **脚本不解析复杂 shell** | hook 只支持 `cd <path>` / `git -C <path>`;其它 ⚠️ 兜底 ctx |
| **失败兜底闭环** | never silent fail |

---

## 九、~~多 cwd 隔离规则~~(v0.1 已 deprecate,见 § 十)

v0.1 用「每 cwd 独立 mem_root」隔离同名分支,但在「workspace 父 cwd + N 个 git 子项目」工作流下退化成单池,反而把不同项目的分支记忆合并到一起。

v0.2 改为按 project-key(git origin)隔离 — 不依赖 cwd,不依赖 git-common-dir,worktree 天然走通。详见 § 十。

---

## 十、多项目 / 多分支隔离规则(v0.2)

### 10.1 隔离矩阵

| 场景 | 处理 | 为何能工作 |
|---|---|---|
| 同 origin 不同 worktree | project_key 同,branch 不同 → 不同 memory 文件 | git-common-dir bug 不再影响我们 |
| 同 origin 不同 cwd 启动(主 cwd / 子 cwd / 别处) | 同 key,同 branch → 同一份 memory | 不再依赖 cwd-slug |
| 不同 origin 但 basename 相同(`org-A/repo` vs `org-B/repo`) | sha1(normalize(origin)) 不同 → 不同 key | normalize 后路径不同 |
| 同 repo SSH↔HTTPS 切换 | normalize 归一后 key 相同 | strip 协议/`.git`/尾斜杠 |
| 非 git repo 的 cwd | 无 key,不进 memex,只走 Claude 原生 | 显式跳过 |
| detached HEAD(checkout 到 commit) | hook 静默放行,不污染 | by_branch 查不到 = 不挂 |
| submodule | 每个 submodule 是独立 repo 有独立 origin | 自然分开 |

### 10.2 实施要点

- `~/.claude/bin/derive_project_key.py` 是单一来源;所有 hook 调它,不自己 hash
- `projects.jsonl.origin_aliases[]` 记录历史 origin,迁移不丢
- `branches.jsonl` 是 hook 的热路径索引,bootstrap/post-checkout/pre-edit 都用它做 O(1) 查找
- 分支死亡 → `alive_on_remote=false`,自动 dormant 进 LRU(§ 四.2)

---

## 十一、索引/规范坏掉的应急

1. **jsonl 损坏**:`jq . <name>.jsonl` 报错 → `python3 ~/.claude/bin/rebuild_index.py`(从 .md 文件重建,LRU 字段保留)
2. **目录结构紊乱**:`~/.claude/memex.pre-apply-backup-*/` 可 rsync 回滚
3. **hook 死循环 / 误拦**:`mv ~/.claude/hooks ~/.claude/hooks.disabled` 临时关
4. **INDEX.md 跟实际不一致**:`python3 ~/.claude/bin/update_index_md.py` 从 jsonl 重生成 INDEX 标记区块
5. **LRU 扫描**:`python3 ~/.claude/bin/lru_compact.py` 列待压缩 / 候选删除清单
6. **project_key 漂了**(origin 变了):手动在 `projects.jsonl` 把旧 key 加进新 key 的 `origin_aliases`
