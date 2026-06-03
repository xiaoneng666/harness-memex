# Memex

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Made for Claude Code](https://img.shields.io/badge/for-Claude%20Code-7B61FF.svg)](https://docs.claude.com/en/docs/claude-code)
[![Bash + Python](https://img.shields.io/badge/Bash%20%2B%20Python-Lightweight-success.svg)]()
[![Status: v0.2.3](https://img.shields.io/badge/Status-v0.2.3-blue.svg)]()

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

`Auto Memory` 是 per-repo 一份 memory;Memex 在它之上补 **project × 分支** 全局池。**v0.2.1 起,project 共享层(overview / 项目 feedback / reference)也彻底跟 cwd 无关** — 任何 cwd / 任何 Claude 进程,一旦碰过 project X 30 天内都自动 @import 它的 INDEX。

实现(v0.2.1):
- `~/.claude/memex/projects/<project-key>/branches/<slug>.md` **每 project 每分支独立 memory**
- project-key 由 `git remote get-url origin` 归一化 + sha1[:12] 派生 — **跨 cwd、跨 worktree 稳定**
- `_index/branches.jsonl` **(project_key, branch) → memory_path 倒排索引(O(1) 查)**
- `post-checkout-handoff.sh` 切分支时**ctx 同回合并行 Read project INDEX + Read to-branch memory + Write from-branch memory**(项目共享层 + 分支层一次拉齐)
- `pre-edit-branch-notice.sh` 编辑前**derive_project_key + ctx 含 project INDEX + 本分支 memory**
- bootstrap 在 Claude `MEMORY.md` 末尾幂等注入 `<!-- memex:bridge -->` 块(@import cwd-发现 + recently-active 项目),**不抢 Auto Memory 写权**
- bootstrap 在 `~/.claude/CLAUDE.md` 末尾幂等维护 `<!-- memex:catalog -->` 块。**v0.2.2 改成极简 manifest(~2KB)取代 @import 全 INDEX**,内容 = 项目目录 + 查询 CLI 用法。任何 cwd 启动都能看到所有项目目录,survive `/compact`(永久 opt-out:`touch ~/.claude/memex/.no_catalog`)
- **按需查询入口(v0.2.2)**:LLM 通过 `python3 ~/.claude/bin/memex_query.py [--list | --project KEY | --branch KEY SLUG | --grep TERM | --health]` 主动拉具体内容,不再预载 INDEX 进 ctx
- hook 触发后异步 `--touch project_key` bump last_access → **碰过的 project 30d 内任何 session 自动 @import**(v0.2.1)

---

## ⚡ 30 秒了解

| Before(裸 Claude Code) | After(装上 Memex) |
|---|---|
| 每次新会话从 0 解释项目背景 | LLM 自动加载本 cwd 的 INDEX + 索引摘要 |
| 切分支忘了上次做到哪 | 切分支自动**收档+启档**,目标分支 memory 内容直接注入 ctx |
| 用户纪律每次都要提醒 | feedback 持久化,Read 时自动续命防 LRU 误杀 |
| memory 越多越难找 | JSONL 索引 O(1) 查,jq 一行命中 |
| 长开发期 context bloat | 30d × 3 次自动压缩,关键决策永久保留 |
| 多项目同名分支串记忆 | project-key(git origin)隔离,worktree / monorepo / 多 cwd 都正确 |
| 一次需求跨 2~9 仓,单仓 memory 看不到全貌(漏拉/漏部署)| `feedback-companion-repo-branches` **recipe(opt-in)**:adopt 后 LLM 自动在分支 memory 加「配合开发的其他仓库分支」段,任一仓切入都见全貌 |

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

### 痛点 7 — 跨仓库联动开发丢全貌
一次业务需求经常跨 2~9 个仓(如 service-a RPC + bff-x 透传 + service-b 拦截)。**只看单仓分支 memory 不知道还动了哪些其他仓的哪些分支** → 容易漏拉、漏合 develop、漏部署。Memex 推荐 [`feedback-companion-repo-branches`](./examples/feedback-companion-repo-branches.md) recipe 强制在分支 memory 列「配合开发的其他仓库分支」(仓 + 分支 + < 20 字关系 + `[[memory]]` 双向链接),任一仓切入都能立刻看到全貌,跟 `branch-naming-consistency` + `report-repos-after-each-change` 三件套形成闭环。

> **注意**:此 recipe 是 **opt-in**,装完 install.sh 不自动启用。**怎么 adopt** 见下方 [推荐 recipes 段](#-推荐的-feedback-recipes纪律模式--opt-in)的「怎么启用某条 recipe」。

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
                │  (7 件套)    │   只塞事实,不做决策
                └──────┬──────┘
                       │ ctx 注入 / 索引同步
        ┌──────────────▼──────────────────────┐
        │  Claude Code 原生(不动)            │
        │  ~/.claude/projects/<cc-slug>/memory/│
        │  └── MEMORY.md ← memex bridge       │
        │       └── @import 下面的 INDEX 们 ──┼─┐
        └──────────────────────────────────────┘ │
        ┌──────────────────────────────────────┐ │
        │  Memex 全局池(项目维度,无 cwd)   │◄┘
        │  ~/.claude/memex/                    │
        │  ├── _index/{projects,branches,meta} │
        │  ├── global/{feedback,reference,...} │
        │  └── projects/<project-key>/         │
        │      └── branches/<slug>.md          │
        └──────────────────────────────────────┘
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

### 7 个 Python CLI 工具

| 工具 | 作用 |
|---|---|
| `derive_project_key.py` | git remote 归一化 + sha1[:12] → project_key(单一身份来源) |
| `update_memex_bridge.py` | 扫 cwd 子目录所有 git repo;在 `~/.claude/CLAUDE.md` 维护 catalog manifest;`MEMORY.md` 维护指示性 bridge |
| **`memex_query.py`**(v0.2.2 新增)| LLM 按需查询入口:`--list` / `--project KEY` / `--branch KEY SLUG` / `--feedback` / `--reference` / `--grep TERM` / `--recent` / `--health` |
| `rebuild_index.py` | 全量重建 3 个 JSONL 索引(LRU 字段保留) |
| `update_index_md.py` | 从索引自动重写 global + 每 project 的 INDEX.md 标记区块 |
| `lru_compact.py` | LRU 周扫 + 分支死亡检测 + `--mark`/`--pin`/`--unpin`/**`--rm`**(三层安全闸门 + 软删 `_trash/`)|
| `migrate_v01_to_v02.py` | v0.1 → v0.2 一次性迁移(YAML mapping 驱动) |

### 关键设计决策(v0.2)

- **JSONL 不是 SQLite** — LLM 可读,无注入,千级规模够,降级简单
- **project-key 而非 cwd-slug 做隔离** — git origin 归一化派生,跨 cwd / 跨 worktree 稳定
- **status × decay 矩阵** — `pinned` 永不淘汰 / `active` 30d 自动 demote / `dormant` 走压缩
- **30d × 3 次压缩** — 90 天到候选删除,再 30d 真删,共 120 天保护期
- **失败兜底 ctx 闭环** — 脚本解析失败 → 塞 ⚠️ ctx 让 LLM 接管,**never silent fail**
- **静态归脚本动态归 LLM** — hook 只支持最简两种 shell 形式,复杂命令一律降级给 LLM
- **不抢 Auto Memory 资源** — bootstrap 在 MEMORY.md 末尾追加 `<!-- memex:bridge -->` 区块,Claude 自己的写入不受影响
- **PostToolUse 切分支 handoff** — Bash 执行完(已切完)塞 ctx,LLM 并行 `Write a-memory` + `Read b-memory`(同回合 2 个 tool call)
- **绕过 [issue #39920](https://github.com/anthropics/claude-code/issues/39920)** — Claude Code 用 `git-common-dir` 派生 slug 在 worktree 下有 bug;memex 直接用 git origin 派生 project-key,worktree 天然走通

详见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)。

---

## 📋 推荐的 feedback recipes(纪律模式 — **opt-in**)

> ⚠️ **Recipes 不是 code feature,装完 install.sh 不会自动启用** — 这些 markdown 文档只是放在 `examples/` 下供用户**主动 adopt**(尊重「不污染用户私人 feedback 池」原则)。LLM 只有看到这些规则进了用户自己的 `~/.claude/memex/global/feedback/`,才会在写 memory 时遵守。

Memex 自带几个**通用纪律模式**,把 spec § 五「signal-only」具体化到日常场景:

| Recipe | 解什么 |
|---|---|
| [`examples/feedback-example.md`](./examples/feedback-example.md) | 单仓的 Why + How to apply + 反例 三段式模板 |
| [`examples/feedback-companion-repo-branches.md`](./examples/feedback-companion-repo-branches.md) | **跨仓库联动闭环**:写分支 memory 必须列「配合开发的其他仓库分支」(仓 + 分支 + 关系 < 20 字 + `[[memory]]`)。新会话切到任一仓都能立刻看到全貌,**避免漏拉 / 漏部署**。配合 `branch-naming-consistency`(跨仓同名)+ `report-repos-after-each-change`(改后报仓)三件套形成跨仓开发闭环 |

### 怎么启用某条 recipe(2 选 1)

**方式 A — 手动 copy(最直接)**

```bash
# 装完 install.sh 后,在 clone 的目录里跑:
cp examples/feedback-companion-repo-branches.md \
   ~/.claude/memex/global/feedback/companion-repo-branches.md

# post-write-memory-sync hook 自动 reindex 进 meta.jsonl
# 下次 session bootstrap 重写 catalog 时,这条会出现在 LLM ctx 里
# 从此 LLM 写分支 memory 时会自动遵守(加「## 配合开发的其他仓库分支」段)
```

**方式 B — 让 Claude 帮你写**

新 session 里说:
> "看 `~/Downloads/harness-memex/examples/feedback-companion-repo-branches.md`,把这条规则写进我的 global feedback。"

Claude 用 Write tool 写到 `~/.claude/memex/global/feedback/`,post-write hook 自动入索引。下次 session LLM 自己看到。

### 验证启用成功

```bash
python3 ~/.claude/bin/memex_query.py --feedback --term companion
# 应看到 companion-repo-branches 出现在 feedback 列表
```

确认在列表里后,LLM 在写**任何分支 memory** 时,都会自动加「## 配合开发的其他仓库分支」段。

### 不想要某条 recipe?

不 adopt 即可(默认就是)。已 adopt 想撤,删 `~/.claude/memex/global/feedback/<slug>.md`,下次 session 自动从 catalog 摘掉。

---

## 📂 它建立的目录结构(v0.2)

```
全局(装一次):
~/.claude/
├── MEMORY_SPEC.md                  单一权威规范(v0.2,11 节)
├── MEMEX_GLOBAL_INDEX_TEMPLATE.md
├── MEMEX_PROJECT_INDEX_TEMPLATE.md
├── hooks/                          7 件套
│   ├── session-bootstrap.sh        薄壳 → update_memex_bridge.py
│   ├── pre-read-memory-bump.sh
│   ├── check-protected-branch.sh
│   ├── pre-edit-branch-notice.sh
│   ├── post-checkout-handoff.sh
│   ├── post-write-memory-sync.sh
│   └── session-start-lru.sh
└── bin/                            6 个 Python 工具
    ├── derive_project_key.py
    ├── update_memex_bridge.py
    ├── rebuild_index.py
    ├── update_index_md.py
    ├── lru_compact.py
    └── migrate_v01_to_v02.py

Memex 全局池(project 维度,无 cwd 维度):
~/.claude/memex/
├── _index/
│   ├── projects.jsonl              project-key → 元数据
│   ├── branches.jsonl              (project_key, branch) → memory_path 倒排(O(1))
│   └── meta.jsonl                  全部 .md 一行(LRU + decay + size)
├── global/
│   ├── INDEX.md                    所有 cwd 都 @import 它
│   ├── feedback/                   跨项目纪律
│   ├── reference/                  跨项目外部引用
│   └── *.md                        跨项目集合文档
└── projects/
    └── <project-key>/              一个 git repo = 一个 key
        ├── INDEX.md                项目门面(被 Claude MEMORY.md @import)
        ├── overview.md
        ├── feedback/               项目专属纪律
        ├── reference/              项目专属外部引用
        ├── *.md                    长期决策
        └── branches/
            └── <branch_slug>.md    分支记忆**只此一份**

Claude Code 原生(我们不动):
~/.claude/projects/<cc-slug>/memory/
└── MEMORY.md                       ← bootstrap 在末尾幂等追加 memex:bridge 块
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
git clone https://github.com/xiaoneng666/harness-memex.git
cd harness-memex
./install.sh
```

`install.sh` 会:
1. 检查依赖
2. 复制 hooks → `~/.claude/hooks/`(7 件套)
3. 复制 bin → `~/.claude/bin/`(6 个 Python 工具)
4. 复制 `MEMORY_SPEC.md` + `MEMEX_GLOBAL_INDEX_TEMPLATE.md` + `MEMEX_PROJECT_INDEX_TEMPLATE.md` → `~/.claude/`
5. 合并 hook 配置进 `~/.claude/settings.json`(自动备份,不覆盖现有)
6. chmod +x

**最后重启 Claude Code**(让 hook 生效)。

### (可选)第 4 步 — adopt 推荐 recipes

`install.sh` 只装 code feature,**不动用户的 feedback 池**。如想启用 [推荐的 feedback recipes](#-推荐的-feedback-recipes纪律模式--opt-in),在 clone 目录里:

```bash
# 例:启用「跨仓库联动闭环」纪律
cp examples/feedback-companion-repo-branches.md \
   ~/.claude/memex/global/feedback/companion-repo-branches.md
```

或新 session 里让 Claude 帮你抄(详见上面 [recipes 段](#-推荐的-feedback-recipes纪律模式--opt-in))。

### 验证装好了

新开会话,任意 cwd 跑一个 bash 让 bootstrap 触发,然后:
```bash
ls ~/.claude/memex/                        # 全局池根:_index/  global/  projects/
cat ~/.claude/memex/_index/projects.jsonl  # 当前识别到的 projects
python3 ~/.claude/bin/memex_query.py --health  # 索引完整性自检
python3 ~/.claude/bin/memex_query.py --feedback # 看已 adopt 的 recipes
```
若看到三层目录 + projects.jsonl 含 cwd 下 git repo,就好了。

---

## 🔧 配置(全部可选)

环境变量在 `~/.zshrc` / `~/.bashrc` 里:

```bash
# 自定义保护分支(默认: main develop production staging)
export MEMEX_PROTECTED_BRANCHES="main master develop staging production release"  # 例子,可加自己仓库的

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
- ✅ ~~不自动跑 LRU 周扫~~ → v0.2 起 `session-start-lru.sh` 在 SessionStart 自动跑,有候选塞 ctx 让 LLM 决定压缩
- ❌ 不替代 git 仓库 — memory 只是你的"个人长期记忆",不入版本控制
- ❌ 不解决 token 成本 — 长 ctx 注入会增加 token

---

## 🗑️ 卸载

```bash
./uninstall.sh
```

会:
- 删 `~/.claude/hooks/{7 件套}.sh` 和 `~/.claude/bin/{6 工具}.py`
- 从 `~/.claude/settings.json` 移除对应 hook 注册(备份保留)
- **保留所有 `~/.claude/memex/`** 和 `~/.claude/projects/*/memory/`(你的工作面不丢)

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

## ❓ FAQ

### Q: 跟 Claude Code 自带的 CLAUDE.md 冲突吗?
**A**:完全不冲突,**互补**。CLAUDE.md 放项目静态元信息,Memex 管动态工作面;bootstrap 在 Auto Memory 的 `MEMORY.md` 末尾幂等追加 `<!-- memex:bridge -->` 区块,内容是 `@import` 全局池 + 有内容项目的 INDEX。**不抢 Auto Memory 写权**。详见 [docs/AUTO-MEMORY-INTEGRATION.md](./docs/AUTO-MEMORY-INTEGRATION.md)。

### Q: 会影响 Claude Code 性能吗?
**A**:几乎无感。hook 平均 < 50ms / 次;post-write-sync 全量 reindex 在 N=50 条时约 30ms;LRU 扫是手动跑,不影响日常。

### Q: 会增加 Claude 的 token 消耗吗?
**A**:**平均略减少**。每次新 session 不用重新解释项目(原来 5-10 分钟 prompt 不再需要);切分支自动注入 memory 替代 LLM 多次 Read。代价是 hook ctx 注入每次平均 200-500 tokens,净效果省下"重新解释"的成本远超 ctx 注入。

### Q: 卸载后 memory 数据丢吗?
**A**:不丢。`uninstall.sh` 只删 hooks + 工具 + settings.json 注册,**所有 memory 数据保留在 `~/.claude/projects/*/memory/`**。重装 `install.sh` 立即接续。

### Q: 跟向量检索 RAG 比怎样?
**A**:**不同的设计目标**。向量 RAG 做语义检索海量非结构化文档,答用户问题;Memex 是结构化的工作面 memory,自动维护 + 自动注入 ctx。两者可以共存:Memex 管"我的工作面",RAG 管"项目文档库"。

### Q: 团队怎么协作?memory 能共享吗?
**A**:**memory 默认是个人的**(在 `~/.claude/` 下)。如果想团队共享:把 `feedback/` 和 `reference/` 软链到一个 git repo 用 PR 协同即可。**branch memory 不建议共享**,它反映个人开发上下文,共享会污染。

### Q: hook 死循环 / 误拦怎么办?
**A**:临时禁:`mv ~/.claude/hooks ~/.claude/hooks.disabled`,排查完再 mv 回来。`install.sh` 改 settings 前必备份(`*.memex-backup-<timestamp>`),恢复 `cp` 回来即可。

### Q: 必须用 Claude Code 吗?Cursor / Aider 能用吗?
**A**:**目前只支持 Claude Code**(基于其 hook API)。理论上可以适配 Cursor / Aider / Cline(它们都有 hook 或 plugin 系统),欢迎贡献。Windows 暂未测试,需 WSL / Git Bash。

> 更多问题(共 20+ 条,含设计哲学 / 故障排查 / 演进):见 [docs/FAQ.md](./docs/FAQ.md)

---

## 📄 许可

[MIT](./LICENSE)

---

如果它帮到你了,点个 ⭐ 让更多人发现。有问题开 issue。有想法开 PR。
