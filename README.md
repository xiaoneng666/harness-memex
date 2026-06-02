# Memex

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Made for Claude Code](https://img.shields.io/badge/for-Claude%20Code-7B61FF.svg)](https://docs.claude.com/en/docs/claude-code)
[![Bash + Python](https://img.shields.io/badge/Bash%20%2B%20Python-Lightweight-success.svg)]()
[![Status: v0.1](https://img.shields.io/badge/Status-v0.1-orange.svg)]()

> **Branch-aware extension pack for Claude Code Auto Memory**
> 致敬 Vannevar Bush 1945 *Memex* 概念

把一次性的 Claude Code 会话,变成**跨会话、跨分支、跨 cwd 持续累积**的长期工作面。

[English](./README.en.md) · [痛点详解](./docs/MOTIVATION.md) · [架构](./docs/ARCHITECTURE.md) · [跟自带 memory 比](./docs/COMPARISON.md) · [5 分钟 Demo](./docs/DEMO.md) · [FAQ](./docs/FAQ.md) · [Roadmap](./docs/ROADMAP.md) · [一键安装](#-安装3-步)

---

## 🌟 核心场景 — 同一 Claude 对话进程内,多项目 × 多分支并行开发

**Anthropic Auto Memory 明文写**(文档原话):*"All worktrees and subdirectories of a project share the same memory directory."* → **Auto Memory 不切分支**。

Memex 补这块:

```
你启动 1 个 Claude 进程,里面可以:

  cwd A (~/proj-a) ─┬─ feat/<date>/login    ← 各自独立 memory
                    ├─ feat/<date>/profile     hook 自动按需切换
                    └─ bugfix/<date>/auth      互不串

  cwd B (~/proj-b) ─┬─ feat/<date>/api-refactor
                    └─ feat/<date>/migration

  cwd C (~/proj-c) ─┬─ main
                    └─ feat/<date>/onboarding
```

同一 Claude 对话进程里,你 bash `cd <subdir> && git checkout <branch>` 自由切换 — **每次切换 hook 自动加载/卸载对应 mem_root,Claude 永远在"正确的工作面里"**。

`Auto Memory` 是 cwd 级一份 memory;Memex 在它之上补 **cwd × 分支** 二维矩阵。

实现:
- `~/.claude/projects/<cwd-slug>/memory/` **每 cwd 独立 mem_root**
- `_index/by_branch.jsonl` **每分支倒排索引**
- `check-protected-branch.sh` 切分支时**收档当前 + 启档目标 + 注入目标 memory 前 200 行进 ctx**
- `pre-edit-branch-notice.sh` 编辑前**用 `cd <path>` / `git -C <path>` 反推子项目分支**
- 严格不跨 cwd glob → **多个项目同名分支不会串**

---

## ⚡ 30 秒了解

| Before(裸 Claude Code) | After(装上 Memex) |
|---|---|
| 每次新会话从 0 解释项目背景 | LLM 自动加载本 cwd 的 INDEX + 索引摘要 |
| 切分支忘了上次做到哪 | 切分支自动**收档+启档**,目标分支 memory 内容直接注入 ctx |
| 用户纪律每次都要提醒 | feedback 持久化,Read 时自动续命防 LRU 误杀 |
| memory 越多越难找 | JSONL 索引 O(1) 查,jq 一行命中 |
| 长开发期 context bloat | 30d × 3 次自动压缩,关键决策永久保留 |
| 多 cwd 同名分支串记忆 | cwd-slug 严格隔离,monorepo 子项目原生支持 |

---

## 🎯 它解决的痛点

如果你重度使用 Claude Code,这些场景一定遇到过:

### 痛点 1 — 跨分支记忆缺失
Claude Code Auto Memory 是 cwd 级一份 memory,**所有 worktree / 子目录共享**(文档明写)。
切了 `feat/X` 分支,memory 还是 cwd 通用那份,不知道你在哪个分支。

### 痛点 2 — 分支切换断档
昨天在 `feat/<date>/X` 做到一半,今天切 `bugfix/<date>/Y` 修 bug,回来 `feat/<date>/X` 时,你**忘了上次写到哪、为什么这么写、还差什么没做**。

### 痛点 3 — 纪律反复重申
"不要直接 commit 到 main"、"测试要用 staging 凭证不用 prod"、"redis 删 key 走 Lua 脚本"——同一条规则每次新会话都要复述。

### 痛点 4 — Memory 黑洞
你写了 50+ 条 .md 当 memory,但**找不到该读哪一条**。Claude 也找不到。

### 痛点 5 — Monorepo 混乱
顶层 cwd 一个,下面 N 个 git 子项目。各项目分支名重复(都叫 `feat/<date>/x`)。memory 串。

### 痛点 6 — 老 memory 不淘汰
Auto Memory 不主动压缩老 memory。3 个月后 200 条混在一起,关键决策跟过期 TODO 没区分。

---

## 💡 Memex 怎么解

**核心哲学:静态规则脚本管,动态判断 LLM 管**(Listener + Handler 模式)

```
              ┌─────────────────┐
              │  Claude Code    │
              │   (Handler)     │
              └────────┬────────┘
                       │ tools (Read/Write/Edit/Bash)
                ┌──────▼──────┐
                │   Hooks     │ ← event listener
                │  (5 件套)    │   只塞事实,不做决策
                └──────┬──────┘
                       │ ctx 注入 / 索引同步
        ┌──────────────▼──────────────┐
        │   ~/.claude/projects/<cwd>/  │
        │   memory/                    │
        │   ├── INDEX.md(人读)          │
        │   ├── _index/*.jsonl(机器索引)│
        │   ├── feedback/(纪律)         │
        │   ├── reference/(外部资源)    │
        │   └── projects/<biz>/         │
        │       └── branches/<slug>.md  │
        └──────────────────────────────┘
```

### 7 个 Hook 干什么(都是 event listener)

| Hook | 触发 | 作用 |
|---|---|---|
| `session-bootstrap.sh` | PreToolUse * | 新 cwd 自动建骨架 / 漂移自动 reindex / **跟 Auto Memory 协作**(@import 注入) |
| `pre-read-memory-bump.sh` | PreToolUse Read | 更新 last_access(防 LRU 误杀 read-heavy)|
| `check-protected-branch.sh` | PreToolUse Bash | commit/push 到保护分支拦截 |
| `pre-edit-branch-notice.sh` | PreToolUse Edit/Write | 编辑前提醒本分支 memory |
| **`post-checkout-handoff.sh`** | PostToolUse Bash | 切分支完成后,塞 ctx 让 LLM **并行 Write a + Read b** |
| `post-write-memory-sync.sh` | PostToolUse Write/Edit | memory 文件改后自动入索引 |
| **`session-start-lru.sh`** | SessionStart | 主动跑 LRU 扫,有候选塞 ctx 让 LLM 决定压缩 |

### 3 个 Python CLI 工具

| 工具 | 作用 |
|---|---|
| `rebuild_index.py` | 全量重建 JSONL 索引(LRU 字段保留) |
| `update_index_md.py` | 从索引自动重写 INDEX.md 标记区块 |
| `lru_compact.py` | LRU 周扫 + 分支删除检测 + `--mark`/`--pin`/`--unpin`/**`--rm`**(三层安全闸门 + 软删 `_trash/`)|

### 关键设计决策

- **JSONL 不是 SQLite** — LLM 可读,无注入,千级规模够,降级简单
- **每个 cwd 独立 mem_root** — 严格隔离,不跨 cwd glob(防同名分支串)
- **status × decay 矩阵** — `pinned` 永不淘汰 / `active` 30d 自动 demote / `dormant` 走压缩
- **30d × 3 次压缩** — 90 天到候选删除,再 30d 真删,共 120 天保护期
- **失败兜底 ctx 闭环** — 脚本解析失败 → 塞 ⚠️ ctx 让 LLM 接管,**never silent fail**
- **静态归脚本动态归 LLM** — hook 只支持最简两种 shell 形式,复杂命令一律降级给 LLM
- **不抢 Auto Memory 资源** — bootstrap 检测 MEMORY.md 状态:不存在 → 软链;Auto Memory 写的 → 末尾追加 `@INDEX.md` 幂等。详见 [AUTO-MEMORY-INTEGRATION.md](./docs/AUTO-MEMORY-INTEGRATION.md)
- **PostToolUse 切分支 handoff** — Bash 执行完(已切完)塞 ctx,LLM 并行 `Write a-memory` + `Read b-memory`(同回合 2 个 tool call)

详见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)。

---

## 📂 它建立的目录结构

```
全局(任何 cwd 共享,装一次):
~/.claude/
├── MEMORY_SPEC.md              单一权威规范(9 节)
├── INDEX_TEMPLATE.md           新 cwd 用的 INDEX 模板
├── hooks/
│   ├── session-bootstrap.sh
│   ├── pre-read-memory-bump.sh
│   ├── check-protected-branch.sh
│   ├── pre-edit-branch-notice.sh
│   ├── post-checkout-handoff.sh        ← PostToolUse 切分支 handoff
│   ├── post-write-memory-sync.sh
│   └── session-start-lru.sh            ← SessionStart 主动 LRU 扫
└── bin/
    ├── rebuild_index.py
    ├── update_index_md.py
    └── lru_compact.py

每个 cwd 自动建出(独立工作面):
~/.claude/projects/<cwd-slug>/memory/
├── INDEX.md                    人读入口 + AUTO 标记区块
├── MEMORY.md → INDEX.md        软链(Claude system prompt 注入)
├── _index/
│   ├── meta.jsonl              每条 memory 一行(LRU + decay + size)
│   └── by_branch.jsonl         (project, branch) → memory 倒排
├── feedback/                   纪律 / 规则(read-heavy)
├── reference/                  外部系统引用
├── user/                       用户画像
├── global/                     跨业务的项目级文档
└── projects/
    └── <business>/
        ├── overview.md
        ├── *.md(长期决策)
        └── branches/
            └── <branch_slug>.md   分支独立工作面
```

---

## 🚀 安装(3 步)

### 依赖

- `jq` — JSON 流处理(macOS: `brew install jq`)
- `python3` ≥ 3.8
- `git`
- [Claude Code](https://docs.claude.com/en/docs/claude-code) CLI

### 安装

```bash
git clone https://github.com/<your-fork>/harness-memex.git
cd harness-memex
./install.sh
```

`install.sh` 会:
1. 检查依赖
2. 复制 hooks → `~/.claude/hooks/`
3. 复制 bin → `~/.claude/bin/`
4. 复制 MEMORY_SPEC / INDEX_TEMPLATE → `~/.claude/`
5. 合并 hook 配置进 `~/.claude/settings.json`(自动备份,不覆盖现有)
6. chmod +x

**最后重启 Claude Code**(让 hook 生效)。

### 验证装好了

新开会话,任意 cwd 跑一个 bash:
```
ls ~/.claude/projects/$(pwd | sed 's#/#-#g')/memory/
```
若看到 `INDEX.md _index/ feedback/ projects/ ...`,就好了。

---

## 🔧 配置(全部可选)

环境变量在 `~/.zshrc` / `~/.bashrc` 里:

```bash
# 自定义保护分支(默认: main master develop production)
export MEMEX_PROTECTED_BRANCHES="main master develop staging production release"

# 自定义 LRU 周期天数(默认: 30)
export MEMEX_LRU_PERIOD_DAYS=30
```

---

## 📖 用起来什么样

### 场景 A:新 cwd 第一次启动 Claude

```
你 cd ~/project/myapp
启动 claude
Claude 跑第一个 bash → bootstrap hook 触发
  → ~/.claude/projects/-Users-x-project-myapp/memory/ 自动建出
  → INDEX.md 是模板,_index/ 空
  → Claude 收到 ctx: "✨ 本 cwd 已初始化,先看 INDEX.md"
```

### 场景 B:你说"记住下次按 conventional commits 写"

```
Claude 在 memory/feedback/conventional-commits.md 写一条
post-write-memory-sync hook 触发 → 自动入 meta.jsonl 索引
下次新会话 INDEX.md 已经把这条列在"反馈/纪律"段
```

### 场景 C:切分支

```
你说"切到 feat/<date>/login"
Claude 跑 cd subdir && git checkout feat/<date>/login
check-protected-branch hook 触发:
  → 收档:当前分支 feat/<date>/profile 的 memory 路径(让 LLM 提醒你补)
  → 启档:目标 feat/<date>/login 的 memory 内容前 200 行直接注入 ctx
  → LLM 切完立即知道之前做到哪
```

### 场景 D:90 天没碰的旧分支

```
你跑 python3 ~/.claude/bin/lru_compact.py
工具列出: 5 条 30d+ dormant 待第 1 次压缩、2 条 60d+ 待第 2 次...
你说"压缩这 5 条"
LLM 逐个 Read → 写紧凑版 → lru_compact.py --mark <path> 1 更新 decay
```

---

## ❓ 不能干啥(已知边界)

- ❌ 不解析复杂 shell(pushd / subshell / 引号路径 / 别名)— **故意如此**,脚本失败时 LLM 兜底
- ❌ 不自动跑 LRU 周扫(手动 `lru_compact.py`,未来 P2 加自动)
- ❌ 不替代 git 仓库 — memory 只是你的"个人长期记忆",不入版本控制
- ❌ 不解决 token 成本 — 长 ctx 注入会增加 token

---

## 🗑️ 卸载

```bash
./uninstall.sh
```

会:
- 删 `~/.claude/hooks/{5 件套}.sh` 和 `~/.claude/bin/{3 工具}.py`
- 从 `~/.claude/settings.json` 移除对应 hook 注册(备份保留)
- **保留所有 `~/.claude/projects/*/memory/`**(你的工作面不丢)

---

## 🤝 贡献

欢迎扩展!路径:
- 新 hook:加在 `hooks/`,在 `install/memex-hooks.json` 加注册
- 新工具:加在 `bin/`,在 `docs/CLI.md` 加用法
- 文档:`docs/` 下任何 .md
- 新 examples:`examples/` 下加场景

详见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

---

## 📚 灵感来源

- **Anthropic** — [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- **Anthropic** — [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- **Vannevar Bush** — [*As We May Think* (1945)](https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/),提出 Memex 概念
- **Linux kernel** — *mechanism not policy*(hook = mechanism,LLM = policy)
- **Redis** — eviction policies(LRU 状态机参照)
- **Nginx** — master-worker 信号控制(hook 失败 silent degrade)

---

## 📄 许可

[MIT](./LICENSE)

---

如果它帮到你了,点个 ⭐ 让更多人发现。有问题开 issue。有想法开 PR。
