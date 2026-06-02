# 为什么需要 Memex — 痛点、功能、作用详解

> 这篇文档详细回答:**Memex 解决什么问题、怎么解的、给你带来什么**。
> 适合给老板/同事/自己看,说明这套东西的工程价值。

---

## Part 1 — 痛点(Why)

### 痛点 1:Claude Code Auto Memory 不分支感知

**症状**:
- Auto Memory 跨 session 学习用户偏好 ✓(Anthropic 已经做了)
- 但 Auto Memory **不切分支**:文档原话 "All worktrees and subdirectories of a project share the same memory directory"
- 你在 feat/X 学到的"踩过的坑",切到 feat/Y 时 memory 仍然是同一份

**根因**:Anthropic 的设计决策(不是 bug),Auto Memory 是 cwd 级。
**Memex 补的**:在 Auto Memory 之上加 cwd × 分支 二维隔离矩阵。

**痛苦量化**:开发一个中型功能 = 10-30 个 session。每个 session 开头 5-10 分钟的"重新介绍" = 整个项目周期浪费 1-3 小时纯重复劳动。

---

### 痛点 2:切分支后 Claude 不知道现在该干啥

**症状**:
- 你 bash `git checkout feat/Y`,Claude 仍然在 feat/X 的上下文里答问题
- 一天切 5 次,每次都要重述"我现在在 Y 分支做 oauth"
- 切回旧分支时,**Claude 不会自动加载旧分支的进度 memory**

**根因**:Auto Memory 是 cwd 级,不感知 git 分支事件。
**Memex 补的**:`post-checkout-handoff.sh` PostToolUse 检测切完成,塞 ctx 让 LLM 主动并行 Write a memory + Read b memory。

**痛苦量化**:每次切分支 + 重新进入状态 ≈ 10-20 分钟。一天切 5 次 = 50-100 分钟 / 天纯 context 重建。

---

### 痛点 3:用户偏好/纪律反复重申

**症状**:
- "不要在 master 直接 commit" — 每个新会话都说一遍
- "测试用 dev 环境的凭证,不用 prod" — 每个新会话都说一遍
- "redis 删 key 走 Lua 脚本" — 每个新会话都说一遍

**根因**:Claude 没有"持久化的纪律库"。CLAUDE.md 可以放一部分,但:
- CLAUDE.md 太长会被压缩
- 没有时间戳 / 重要性分级 / LRU 维护
- 跨 cwd 不共享

**痛苦量化**:每条纪律每次重申约 30 秒。50 条纪律 × 10 session = 250 分钟 / 月。还没算"忘了重申导致 Claude 真做错"的代价。

---

### 痛点 4:Memory 黑洞

**症状**:
- 你写了 50+ 条 .md 当 memory(架构决策、踩坑记录、TODO)
- 想找"上次那个奇怪的 cache 问题"的笔记 — 翻不到
- Claude 也找不到 — 它只能 grep,grep 慢且不精确

**根因**:**memory 没有索引**。文件多了就是文件夹爆炸,没有 metadata、没有 last_access、没有 tag。

**痛苦量化**:有用的 memory 沉在没用的里,**实际利用率 < 10%**。

---

### 痛点 5:Monorepo / 多 cwd 工作流串

**症状**:
- 顶层 cwd 一个,下面有 N 个 git 子项目
- 子项目 A 和 B 都有 `feat/<date>/login` 分支
- Claude 切到 A 的 login,加载了 B 的 memory — 完全错乱

**根因**:Claude 平台按 cwd 隔离 memory,但用户的工作流是**主 cwd 启动 Claude + cd subdir 跑命令**。hook 拿不到正确的 git 仓库根。

**痛苦量化**:多子项目场景下,Claude 的 branch-aware 行为完全失效。

---

### 痛点 6:长开发周期 context bloat

**症状**:
- 项目跑了 3 个月,memory 累积到 200 条
- 大部分是 1-2 周前的旧决策,**早就不相关**了
- 但 INDEX.md 里全是,Claude 每次 Read 上下文都被填满

**根因**:**没有 LRU**。Memory 只增不减,关键决策跟过期 TODO 混在一起。

**痛苦量化**:context window 浪费 50%+ 在历史噪音上。

---

### 痛点 7:Hook 哑火 / silent fail

**症状**:
- 装了 hook 自动维护 memory,但某次 jq 升级 / PATH 变化
- hook 静默挂掉,memory 不再自动入索引
- 你以为系统正常,实际**一个月没维护**才发现

**根因**:hook stderr 不进 Claude 上下文,**用户和 LLM 都看不到 hook 死了**。

---

## Part 2 — Memex 怎么解(How)

### 解 1:三层目录 + JSONL 索引

```
~/.claude/                          全局,任何 cwd 共享
├── MEMORY_SPEC.md                  规范单一权威
├── hooks/  (7 件套)                 event listener
└── bin/    (3 工具)                 python CLI

~/.claude/projects/<cwd-slug>/memory/    每 cwd 独立
├── INDEX.md
├── _index/                         机器索引
│   ├── meta.jsonl                  每条 memory 一行(LRU + decay + size)
│   └── by_branch.jsonl             (project, branch) → memory_path 倒排
├── feedback/                       纪律
├── reference/                      外部资源
├── global/                         跨业务的项目级
└── projects/<biz>/
    ├── overview.md
    └── branches/<slug>.md
```

**对痛点 1**:全局规范 + 每 cwd 独立工作面 → 每次新 session 自动加载 INDEX.md → Claude 一上来就知道项目背景
**对痛点 4**:jq 索引 O(1) 查询 → 千级 memory 一行命令命中

### 解 2:Listener + Handler 哲学

```
事件(git/Edit/Read/Bash)
     ↓
hook 监听(确定性,机器层)   ← 7 件套
     ↓ 把"事实"塞 ctx
LLM 收到 ctx(语义层,动态)
     ↓ 自决策做什么
Write/Edit memory(persistent state)
```

- **静态规则脚本管**:保护分支拦截、索引同步、last_access 维护、bootstrap
- **动态判断 LLM 管**:写什么 memory、怎么压缩、是否切分支、是否更新

**对痛点 7**:hook 失败时通过 `hookSpecificOutput.additionalContext` 塞 ⚠️ ctx,LLM 看得到 → 接管

### 解 3:7 个 Hook(event listener)

| Hook | 解的痛点 | 怎么解 |
|---|---|---|
| `session-bootstrap.sh` | #1 #5 | 新 cwd 自动建骨架 + 检测索引漂移自动 reindex |
| `pre-read-memory-bump.sh` | #3 | Read feedback 自动更新 last_access,LRU 不误杀 |
| `check-protected-branch.sh` | #2 | 切分支收档+启档,目标 memory 内容直接注入 ctx |
| `pre-edit-branch-notice.sh` | #2 | 编辑前提醒本分支 memory,防 LLM 写错分支 |
| `post-write-memory-sync.sh` | #4 | memory 文件改后自动入 jsonl 索引 |

### 解 4:LRU 30d × 3 次压缩

```
status × decay 状态机:

active   + last_access < 30d  → 不动
active   + last_access ≥ 30d  → 隐式 demote 到 dormant,待第 1 次压缩
dormant  + decay 0→1→2→3       → 每 30d 压缩一次,目标 size 递减(2KB → 800B → 300B)
dormant  + decay=3 + 又 30d    → status=candidate_to_delete,通知用户
candidate_to_delete + 用户授权  → rm + 移除索引行
pinned                         → 永不淘汰(用户显式锁)
```

**对痛点 6**:旧 memory 自动压缩成骨架,关键 Why/决策保留,流水账消失
**对痛点 3**:Read 自动续命,read-heavy 的 feedback 永远活着

### 解 5:多 cwd 严格隔离 + monorepo 支持

- 每个 cwd 独立 mem_root,hook 不跨 cwd glob
- check-protected-branch 解析 `cd <path>` / `git -C <path>` 拿子项目分支
- pre-edit-branch-notice 从 file_path dirname 反推 git 根

**对痛点 5**:子项目 A 的 `feat/<date>/x` 不会串到 B

### 解 6:失败兜底 ctx 闭环

```bash
# 之前(silent fail):
hook 解析失败 → exit 0(LLM 不知道)

# 现在(兜底闭环):
hook 解析失败 → 塞 ⚠️ ctx → LLM 接管:
  "⚠️ 我没识别 cmd 格式,请你自己拿当前分支,看是否要写 memory"
```

**对痛点 7**:never silent fail。脚本不工作 LLM 立即知道。

---

## Part 3 — 你的实际收益(What)

### 时间节省(估算)

| 痛点 | 之前 | 用 Memex 之后 | 节省 |
|---|---|---|---|
| 每 session 重新解释项目 | 5-10 分钟 × 30 session = 4-5 小时 / 月 | 自动加载 INDEX.md = 0 分钟 | **4-5 小时 / 月** |
| 切分支重新进入状态 | 10-20 分钟 × 5 次/天 = 50-100 分钟/天 | hook 注入 memory = 1-2 分钟 | **40-90 分钟 / 天** |
| 重申纪律 | 30 秒 × 50 条 × 10 session = 4 小时 / 月 | feedback 持久化 = 0 分钟 | **4 小时 / 月** |
| 找历史 memory | 平均 2-5 分钟 / 次 | jq 一行命中 = 0.5 秒 | 95% 时间节省 |

**总计**:粗估每天节省 1-2 小时纯重复劳动 + Claude 决策质量明显提升(因为它有更完整的项目上下文)。

### 质量提升

1. **决策连贯性**:跨 session 的架构决策不会被遗忘
2. **纪律执行率**:保护分支拦截 + 编辑前提醒 → "误 commit 到 master" 直接清零
3. **Onboarding 加速**:新人入项目时,看 INDEX.md + projects/<biz>/overview.md 就能秒上手
4. **可审计**:每条 memory 有 last_access / decay / size,可以审"哪些决策最近被引用"

### 工程优雅

1. **零侵入**:不改 Claude 本身,只装 hook + 工具
2. **零锁定**:memory 都是 plain markdown + jsonl,卸载后文件仍在
3. **可降级**:任何 hook 失败,LLM 自动兜底,从不阻断
4. **可演进**:加新 hook = 加文件 + 注册;改 LRU 周期 = 一个环境变量

---

## Part 4 — 不能干啥(诚实边界)

- ❌ **不解析复杂 shell**(pushd / subshell / 引号路径 / 别名)— 故意如此,LLM 兜底
- ❌ **不自动跑 LRU 周扫**(手动 `lru_compact.py`,未来 P2 加自动)
- ❌ **不替代 git** — memory 只是个人长期记忆,不入版本控制
- ❌ **不减少 token 成本** — ctx 注入会增加 token(但减少"重新解释"消耗的 token 远超它)
- ❌ **不支持 Cursor / Aider 等** — 当前实现绑 Claude Code hook API;未来可移植

---

## Part 5 — 跟 alternatives 的对比

| 方案 | 跨 session 持久化 | 自动维护 | 索引 | LRU | hook 集成 |
|---|---|---|---|---|---|
| CLAUDE.md | ✓(项目根)| ✗ | ✗ | ✗ | ✗ |
| `/resume` | 一次性 | ✗ | ✗ | ✗ | ✗ |
| MCP memory server | ✓ | ✓ | 向量 | ✗ | ✗ |
| 自己手写 .md | ✓ | ✗ | ✗ | ✗ | ✗ |
| **Memex** | ✓ | ✓ | jsonl | ✓ | ✓ |

Memex 不替代 CLAUDE.md(那是项目元信息),也不替代 MCP memory(那是向量检索)。**它填补的是"工程化的长期工作面"这块空白**。

---

## 总结一句话

> **把一次性的 AI 对话,变成可以累积、可以查询、可以自我维护的长期记忆系统。**
