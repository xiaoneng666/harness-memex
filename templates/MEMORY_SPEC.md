# Memory 系统 — 全局规范(任何 cwd / 任何 Claude 进程都遵守)

> 这份规范是**所有 Claude 工作面 memory 的工程约束**,不是某一个项目的规则。
> 任何新 cwd 第一次启动时,`~/.claude/hooks/session-bootstrap.sh` 会自动建出符合本规范的目录骨架。

---

## 一、目录结构(三层)

每个 cwd 对应一个 `~/.claude/projects/<cwd-slug>/memory/`,内部固定为:

```
memory/
├── INDEX.md                  ← 人读入口(LLM 启动时通常先读这个)
├── MEMORY.md                 ← 软链接 → INDEX.md(系统提示词向前兼容)
├── _index/                   ← 机器索引(harness 关键,hook 用)
│   ├── meta.jsonl            每条 memory 一行元数据(LRU + decay + size)
│   └── by_branch.jsonl       (project, branch) → memory_path 倒排索引
├── feedback/                 用户硬性纪律 / 反馈规则(本 cwd 范围)
├── reference/                外部系统引用(API 地址 / 凭证等)
├── user/                     用户画像
├── global/                   跨业务项目的项目级文档(技术栈等)
└── projects/                 按业务项目分组的工作面 memory
    └── <project>/
        ├── README.md         (可选)项目级 INDEX
        ├── overview.md       项目长期决策
        ├── *.md              其它长期文档
        ├── branches/         分支记忆
        │   └── <branch_slug>.md
        └── _archive/         (可选)已压缩 / 已关闭的归档
```

**slug 规范**:`/` 和 `-` 替换成 `_`(如 `feat/<date>/example-feature` → `feat_0531_example_feature`)。

## 二、JSONL 索引 schema(机器解析)

### `_index/meta.jsonl`(每条 memory 一行)
```json
{
  "path": "projects/example-project/branches/feat_0531_example_feature.md",
  "type": "branch",
  "project": "example-project",
  "branch": "feat/<date>/example-feature",
  "name": "project-branch-feat-0531-example-feature",
  "description": "一句话摘要",
  "status": "active",
  "last_access": "2026-06-02T16:00:00Z",
  "decay": 0,
  "size": 3836
}
```

**字段约束**:
- `path` — 相对 `memory/` 根路径
- `type` — `feedback` / `reference` / `user` / `global` / `project` / `branch`
- `project` / `branch` — 工作面 memory 才有值,其它为空字符串
- `status` — `active`(默认) / `dormant` / `pinned` / `candidate_to_delete`
- `last_access` — ISO8601 UTC,由 `~/.claude/hooks/pre-read-memory-bump.sh` 在每次 Read 时更新
- `decay` — 0 / 1 / 2 / 3,压缩次数,3 = 候选删除
- `size` — 字节数,压缩效果监测

### `_index/by_branch.jsonl`(分支倒排,hook 切分支查这个)
```json
{
  "project": "example-project",
  "branch": "feat/<date>/example-feature",
  "memory": "projects/example-project/branches/feat_0531_example_feature.md"
}
```

**查询语句**(hook 用 jq,**只查当前 cwd 对应的 mem_root**,不跨 glob,见 § 九):
```bash
mem_root="$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory"
jq -r --arg b "$branch" 'select(.branch==$b) | .memory' \
  "$mem_root/_index/by_branch.jsonl" | head -1
```

## 三、LRU 淘汰策略(状态机,30d 周期 × 3 次压缩)

| `status` | `decay` | 何时进 | LRU 工具看到时的 stage |
|---|---|---|---|
| `active` | 0 | 默认起始 / `last_access < 30d` | `active`(不动)|
| `active` | 0 | `last_access ≥ 30d` | `pending_compact_1`(隐式 demote dormant,LLM 压缩后写回 `status=dormant decay=1`)|
| `dormant` | 1 | 又 30d 未 access | `pending_compact_2` → LLM 压缩到 `decay=2` |
| `dormant` | 2 | 又 30d 未 access | `pending_compact_3` → LLM 压缩到 `decay=3` |
| `dormant` | 3 | 又 30d 未 access | `pending_delete` → 标 `status=candidate_to_delete`,**通知用户** |
| `candidate_to_delete` | 3 | **用户授权** | `rm` + 从 `meta.jsonl` / `by_branch.jsonl` 移除 |
| `pinned` | - | **用户显式锁** | `pinned`(永不淘汰,即使一年没 access)|

**关键约束**:
- **status=pinned 才永不淘汰**(用户显式标的开发中分支 / 持续重要的纪律);**status=active 默认会自动按 last_access 走 LRU**
- 压缩内容**由 LLM 做**(理解上下文后写出紧凑版),工具只列候选 + 改 decay/status
- **删除前必须用户授权**(`status=candidate_to_delete` 通知,等"删"指令)
- `last_access` 由 hook 自动维护,**LLM 不要手动改**
- 周期可配:`export MEMEX_LRU_PERIOD_DAYS=30`;默认 30
- 显式锁定某条:`python3 ~/.claude/bin/lru_compact.py --pin <rel_path>`;解锁 `--unpin`

### 三.A 压缩 SOP(LLM 触发后做什么)

工具 `~/.claude/bin/lru_compact.py` 扫到 dormant 候选后,输出待压缩清单。LLM 拿到清单:
1. **逐条 Read 该文件全文**(可以并行 Read)
2. **按 decay 级别写紧凑版**,Write 回原路径覆盖:
   - decay 0→1:保留 frontmatter + Why / 关键决策 / 当前状态 / 链接,目标 size ≤ 2KB
   - decay 1→2:保留 frontmatter + 1-2 段核心 + 链接,目标 size ≤ 800B
   - decay 2→3:保留 frontmatter + 1-3 句精华 + 链接,目标 size ≤ 300B
3. **写完后跑** `lru_compact.py --mark <rel_path> <new_decay>` 更新 jsonl

### 三.B 分支删除 → 进 LRU

工具 `python3 ~/.claude/bin/lru_compact.py --detect-deleted-branches <repo_path>` 对所有 `type=branch` 的 memory:
- 一次性 `git for-each-ref refs/heads` + `refs/remotes` 拿所有存活分支
- **本地远程都查不到** → 该 memory 立即 `status=dormant`(并入下一周期 LRU 流程)

**触发时机**:目前手动跑;未来 P2 加 SessionStart hook 周期触发 / cron。

### 三.C decay 字段的写回方式

LLM 压缩完文件后,**不要手动改 meta.jsonl**(会出错)。改用:
- 工具 `lru_compact.py --mark <rel_path> <new_decay>` 增量更新 meta.jsonl 单条记录
  - 省略 mem_root 时默认用**当前 cwd 对应的 mem_root**(规则同 § 九)
  - `decay=0` → status=active;`decay>0` → status=dormant
- 锁定某条永不淘汰:`lru_compact.py --pin <rel_path>` / 解锁 `--unpin`

## 四、写 memory 的纪律(harness 风格)

只记**主要的**,不堆细节:

| 该记 | 不该记 |
|---|---|
| ✅ 改动(高层 — 哪些文件,做了什么改造) | ❌ 每行 diff |
| ✅ 状态(已部署 / 已 merge / 待修 / 已废弃)| ❌ commit hash 全清单(给出关键 1-2 个就行)|
| ✅ 思路(Why / 架构决策 / 踩坑教训) | ❌ 详细技术叙述(那是 commit message / PR 描述的事)|
| ✅ 进度(完成度 / 阻塞点 / 下一步) | ❌ 时间日志 |

frontmatter 固定:
```yaml
---
name: <kebab-case-slug>
description: <一句话摘要,索引里展示用>
metadata:
  type: feedback|reference|user|project|branch|global
---
```

**新加 memory 后必入索引**(任何一条都要,无例外):
- Write/Edit 到 `memory/**/*.md` 路径 → `post-write-memory-sync.sh` 自动增量同步进 jsonl
- 这是**自动的**,LLM 不用手动跑工具
- 同步失败 → 通过 hookSpecificOutput.additionalContext 抛 ⚠️ ctx,LLM 看得到 → 手动 fallback

## 五、Hook 行为(全局生效)

| Hook 文件 | 触发 | 动作 |
|---|---|---|
| `session-bootstrap.sh` | PreToolUse(任何工具)| 检测 `_index/` 缺失或漂移 → 自动建骨架 + rebuild_index + Auto Memory 协作(@INDEX.md)|
| `pre-read-memory-bump.sh` | PreToolUse Read | Read 路径在 `memory/**/*.md` → 更新 `meta.jsonl` 的 `last_access` |
| `check-protected-branch.sh` | PreToolUse Bash | git commit/push 到保护分支拦截(checkout/switch 段移到 post-checkout-handoff)|
| `pre-edit-branch-notice.sh` | PreToolUse Edit/Write | 每 session 每分支首次编辑提醒分支 memory |
| `post-checkout-handoff.sh` | PostToolUse Bash | git checkout/switch 成功后,塞 ctx 让 LLM **并行 Write a + Read b** |
| `post-write-memory-sync.sh` | PostToolUse Write/Edit/MultiEdit | file_path matches `memory/**/*.md` → 自动增量入索引 |
| `session-start-lru.sh` | SessionStart | 主动跑 `lru_compact.py --quiet`,有候选塞 ctx 让 LLM 自决策压缩 |

**Hook 工程纪律**:
- 失败永远 `exit 0`(不阻断 LLM 工作)— 除了保护分支拦 commit/push 那个故意 exit 2
- 输出错误到 stderr **同时** 通过 hookSpecificOutput.additionalContext 抛给 LLM
- 写 jsonl 必须 tmpfile + mv(原子)
- 同 session 同 cwd 同分支去重(`/tmp/harness-memex-*-marker`)
- 索引坏掉 → fallback 到 `ls projects/*/branches/<slug>.md` 全盘 glob
- **hook 只查当前 cwd 对应的 mem_root,不跨 cwd glob**(防同名分支串)

## 六、Bootstrap(新 cwd 自动适配)

逻辑:
1. `cwd_memory=~/.claude/projects/<cwd-slug>/memory/`
2. 若 `cwd_memory` 不存在 → 自己 `mkdir -p`
3. 若 `_index/` 已存在 → 检查 `_index/meta.jsonl` 行数是否等于 .md 文件数;不等则增量 rebuild_index
4. 若 `_index/` 不存在 → 建骨架 + 复制 INDEX_TEMPLATE.md + 跑 rebuild_index

## 七、Harness 工程原则(贯穿所有改动)

| 原则 | 在 memory 系统的体现 |
|---|---|
| **单一职责** | 每个 hook 做一件事(bootstrap / checkout handoff / last_access bump / branch notice / write sync 各自独立)|
| **幂等** | bootstrap 检测目录存在跳过;jsonl 更新用 tmpfile+mv;同输入同输出 |
| **零状态/确定性** | 索引完全由 `.md` 文件 + 路径推导;重建索引始终得同样结果 |
| **可观测** | hook 错误到 stderr,LLM 看得到 |
| **可降级** | jsonl 坏掉 → fallback glob;`jq` 缺失 → fallback grep |
| **可演进** | jsonl 新增字段不破坏老查询(jq 忽略未知字段)|
| **可回滚** | 任何迁移前先 `cp -r memory memory.backup-<date>`,改坏直接 mv 回去 |
| **隔离** | 每个 cwd 自己的 mem_root,hook 不跨 cwd(见 § 九)|
| **脚本不解析复杂 shell** | hook 只支持两种最简形式:`cd <path>; git ...` / `git -C <path> ...`。**任何新 shell 模式(pushd / subshell / 引号路径 / 别名 / env vars)一律 NOT FIX**。脚本不理解时塞 ⚠️ 兜底 ctx,让 LLM 看上下文自决策。违反这条的 PR 不论测试多漂亮先删代码。|
| **失败兜底闭环** | hook 解析失败 / 索引同步失败 → 用 `hookSpecificOutput.additionalContext` 塞 ⚠️ ctx 给 LLM(不只是 stderr,LLM 看不到);LLM 看 ctx + 上下文 + spec 自决策。不允许 silent fail。|

## 八、索引/规范坏掉的应急

1. **jsonl 损坏**:`jq . meta.jsonl` 报错 → 跑 `python3 ~/.claude/bin/rebuild_index.py`(从 .md 文件重建,LRU 字段保留)
2. **目录结构紊乱**:`memory.backup-<date>/` 还在,可以 rsync 回滚
3. **hook 死循环 / 误拦**:`mv ~/.claude/hooks ~/.claude/hooks.disabled` 临时关 hook
4. **INDEX.md 跟实际不一致**:`python3 ~/.claude/bin/update_index_md.py` 从 meta.jsonl 重生成 INDEX 的标记区块
5. **LRU 扫描**:`python3 ~/.claude/bin/lru_compact.py` 列待压缩 / 候选删除清单(详见 § 三.A)

## 九、多 cwd / 多项目 / 多分支隔离规则

Claude 平台默认按 cwd 路径建独立 mem_root(`~/.claude/projects/<cwd-slug>/`),本规范严格遵守此隔离:

| 场景 | 处理 | 不会发生 |
|---|---|---|
| 同一 Claude session 切换不同 cwd | 每个 cwd 第一次 bash 触发各自 bootstrap | 跨 cwd memory 串 |
| 同一 cwd 内多分支 | 单 cwd 内分支唯一(原则) → by_branch.jsonl 一键命中 | 同 cwd 同分支重 |
| 多 cwd 同名分支(repo A / repo B 都有 `feat/<date>/x`) | hook 只查当前 cwd 的 by_branch.jsonl,**不跨 cwd glob** | A 拿到 B 的 memory |
| 同 cwd 含多个 git 子仓库(monorepo) | hook 用 `cd <path>` / `git -C <path>` 拿子项目分支 | 子仓库串顶层 |
| git worktree(同 repo 多 worktree) | 每个 worktree 是独立 cwd → 各自独立 mem_root | worktree 间串 |
| detached HEAD(checkout 到 commit hash) | hook target=hash → by_branch 查不到,静默放行 | 用 commit hash 当分支名污染 |

**实施要点**:
- `lookup_branch_memory()` 函数只查 `$HOME/.claude/projects/$(pwd | sed 's#/#-#g')/memory/_index/by_branch.jsonl`,不跨 cwd glob
- 删除某分支(本地 + 远程都查不到)→ 自动 `status=dormant` 进 LRU(§ 三.B)
- 切换 cwd / 切换 worktree → bootstrap 自动给新 cwd 建骨架(若缺)
