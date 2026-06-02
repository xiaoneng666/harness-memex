# Architecture — 设计哲学与决策记录

> Memex 不是把 ChatGPT 的 memory 抄一遍。它是按 **Anthropic Effective Harnesses for Long-Running Agents** + **Linux kernel mechanism vs policy** + **Redis eviction policy** 的工程哲学,**专为 Claude Code 的 hook 系统**设计的长期记忆 + 自动化 harness。

## 核心哲学:Listener + Handler

```
              ┌─────────────────┐
              │  Claude Code    │   动态判断
              │   (Handler)     │   语义层
              └────────┬────────┘
                       │ tools (Read/Write/Edit/Bash)
                ┌──────▼──────┐
                │   Hooks     │   事件监听
                │  (5 件套)    │   机器层 / 确定性
                └──────┬──────┘
                       │ 塞事实 ctx + 索引同步
        ┌──────────────▼──────────────┐
        │   Memory(persistent state)  │
        │   markdown + jsonl 索引       │
        └──────────────────────────────┘
```

### 责任边界

| 层 | 干什么 | 不干什么 |
|---|---|---|
| **Hooks(脚本)** | 确定性事件(commit/push 拦截 / 索引同步 / last_access 维护 / bootstrap)| 解析复杂 shell / 判断"是否要写 memory" / 选 compaction 内容 |
| **LLM(Claude)** | 动态决策(写什么、怎么压缩、是否切分支、是否更新)| 维护索引、处理保护分支拦截、记录 last_access |

这个划分是从 **Linux kernel 的 mechanism vs policy** 借来的:
- 内核(机制层)提供工具:进程调度、内存分配、IO
- 用户空间(策略层)决定:什么时候调度谁、内存怎么分

Memex 的 hook = mechanism,LLM = policy。

## 关键决策

### 决策 1:为什么 JSONL 不是 SQLite

| 维度 | JSONL | SQLite |
|---|---|---|
| LLM 可读 | ✓ jq 一行 / cat 看 | ✗ 二进制 |
| 注入风险 | 0 | SQL injection |
| 千级规模 | 够(50KB / 1000 行)| 杀鸡用牛刀 |
| 降级 | jq 不在 → grep | 没工具就废 |
| 工具链 | jq 全平台 | sqlite3 多平台但更重 |
| schema 演进 | 加字段不破坏 | 需 migration |

我们要的是"轻量、可读、可降级",JSONL 完胜。规模到 10000+ 条时再考虑迁移。

### 决策 2:为什么每 cwd 独立 mem_root,不共享 feedback

**问题**:用户的纪律(比如"redis 走 Lua")是不是该全局共享?

**反对方**:纪律是跨项目的,共享更省。
**赞成方(采纳)**:不同项目的纪律不同(Go 项目和 Python 项目纪律差远),共享会污染。隔离最简单。

**结果**:每 cwd 一份 feedback。重复条目 = 用户主动维护(可以软链接同一文件)。

### 决策 3:为什么 LRU 30d × 3 次压缩,不是直接删

**反对方**:30d 没访问就该删,90 天 + 3 次压缩太啰嗦。
**赞成方(采纳)**:Memory 是**关键 Why / 决策**,不是流水账。直接删会丢架构史。3 次压缩让内容从"流水账"逐步退化成"骨架",**关键 Why 永远保留**。120 天才真删,留足缓冲。

### 决策 4:为什么 status=pinned 永不淘汰,active 自动 demote

**初版设计**:status=active 永不淘汰,要手动改 status 才进 LRU。
**问题**:用户从不主动改 status,**LRU 永远空转**。
**修法(采纳)**:status=active 默认随 last_access 自动 demote dormant。status=pinned 才是真正的"永不淘汰"(用户显式锁的开发中分支 / 持续重要纪律)。

### 决策 5:为什么 hook 不解析复杂 shell

**反对方**:加几个 case 就能覆盖更多 cmd 格式(pushd / subshell / 引号路径)
**赞成方(采纳)**:每加一个 case,要加测试 + 回归测试 + 边界处理。shell 命令是无限的,这是无底洞。**hook 只支持两种最简形式**(`cd <path>` / `git -C <path>`),其它一律 ⚠️ 兜底 ctx 让 LLM 接管。

这个原则刻进了 `MEMORY_SPEC.md § 七`:
> **脚本不解析复杂 shell**:违反这条的 PR 不论测试多漂亮先删代码。

### 决策 6:为什么 hook 失败要塞 ctx 而不是 silent exit 0

**之前**:hook 失败 `exit 0`,不阻断 LLM。
**问题**:LLM 不知道 hook 试过又失败了 → 不会接管 → memory 系统静默坏掉。
**修法(采纳)**:hook 失败时通过 `hookSpecificOutput.additionalContext` 塞 ⚠️ ctx,告诉 LLM "我没识别,你看着办"。LLM 看 ctx + spec + 上下文自己接管。

**核心原则**:silent degrade 不等于 silent fail。Degrade = 退到 LLM 兜底;Fail = 谁都不知道。

## Harness 工程原则(贯穿所有改动)

| 原则 | 实现 |
|---|---|
| **单一职责** | 5 个 hook 各干一件事,不耦合 |
| **幂等** | bootstrap 检测存在跳过;jsonl 用 tmpfile+mv |
| **零状态/确定性** | 索引完全由 .md + 路径推导;rebuild 结果同样 |
| **可观测** | hook 错误到 stderr + LLM ctx |
| **可降级** | jsonl 坏 → glob;jq 缺 → grep;hook 失败 → LLM 兜底 |
| **可演进** | jsonl 加字段不破老查;新 hook 加文件即可 |
| **可回滚** | 迁移前先 `cp -r memory memory.backup-<date>` |
| **隔离** | 每 cwd 独立 mem_root |
| **脚本不解析复杂 shell** | hook 失败 → ⚠️ ctx → LLM 兜底 |
| **失败兜底闭环** | never silent fail |

## 灵感来源 — 顶级 AI 团队 + 经典工程作品

我们**不重复造轮子**。下面每条都是 Memex 某个设计的根。

### AI 团队公开实践

| 来源 | 借鉴的思想 | 在 Memex 的体现 |
|---|---|---|
| [**Anthropic** — Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | 长跑 agent 的 4 种失败模式(context rot / tool error / hallucination / drift)| hook 兜底 ctx 闭环 + silent degrade(never silent fail)|
| [**Anthropic** — Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | tiered memory + compaction + sub-agent handoff | LRU 30d × 3 次压缩 + status × decay 状态机 |
| [**Anthropic** — Prompt Caching (refresh-on-use)](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | 5 分钟 TTL + read-on-access refresh | `pre-read-memory-bump.sh` 维护 last_access 防 LRU 误杀 |
| [**Anthropic** — Writing Tools for Agents](https://www.anthropic.com/engineering/writing-tools-for-agents) | 工具塞事实不下决策 | hook 只塞事实(path + branch + ctx)不下 SOP |
| **Anthropic** — Claude Memory Tool(Claude Code 4.x auto-memory) | 自动注入 system prompt | 互补不替代:CLAUDE.md 静态,Memex 动态(见 [COMPARISON.md](./COMPARISON.md))|
| [**OpenAI** — GPT-4.1 Prompting Guide](https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide) | Persistence / Tool-calling / Planning agent 三件套 | hook + LLM 的 listener/handler 分工 |
| [**Letta / MemGPT** — "LLM as Operating System"(Packer et al. 2023)](https://arxiv.org/abs/2310.08560) | tiered memory(main / external)+ paging | status × decay 4 阶状态机 + LRU 触发 |
| [**Voyager**(NVIDIA Jim Fan et al.)](https://voyager.minedojo.org/) | Minecraft 长跑 agent 的 skill library memory | "按 cwd × 分支"的工作面分库思路 |
| [**Generative Agents**(Stanford, Park et al. 2023)](https://arxiv.org/abs/2304.03442) | memory stream + reflection + retrieval | 未来 P3 的 reflection agent 路线 |
| **Andrej Karpathy** — "LLM OS" 概念 | LLM = CPU, memory = file system | hook + JSONL = OS-level scheduler + file metadata |
| [**Cognition Devin** — long-running agent](https://www.cognition.ai/blog) | 持续多天的 agent 任务调度 + memory | 跨 session 的工作面累积设计 |

### 经典工程作品

| 来源 | 借鉴的思想 | 在 Memex 的体现 |
|---|---|---|
| **Linux kernel** | mechanism vs policy(Lions' Commentary / Tanenbaum)| hook = mechanism, LLM = policy(强制责任分离)|
| **Redis** — [eviction policies](https://redis.io/docs/manual/eviction/) | allkeys-lru / volatile-lfu / noeviction + 近似 LRU | status × decay:pinned ≈ noeviction,active 自动 demote ≈ allkeys-lru |
| **Nginx** — master-worker + signal control | 失败 silent-degrade + 优雅 reload | hook 失败 exit 0 + ⚠️ ctx fallback 给 LLM(信号控制) |
| **DDIA 第 3 章** — 索引设计(Martin Kleppmann) | append-only + inverted index | JSONL + by_branch.jsonl 倒排索引 |
| **Vannevar Bush** — [*As We May Think* (1945)](https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/) | Memex = associative trails of memory | 项目名 + `[[xxx]]` 内部链接的 associative trails |

### 为啥这么多参考?

因为 **memory + harness for agents 是个真问题**,顶级 AI 团队都在攻:

- Anthropic 在 system prompt + caching 层做
- OpenAI 在 ChatGPT 服务端做  
- Letta 在 framework 层做
- Cursor 在 IDE 层做
- Cognition Devin 在 agent loop 层做

**Memex 在 Claude Code hook 层做** — 是没人占的空白,但也是离用户开发工作流最近的地方。每个事件触发、每个文件维护,都对应一条公开实践。**抄好抄满 + 自己补缺**。

## 拓展点(欢迎 PR)

- 新事件 hook:比如 PreCompact(在 Claude 压缩 ctx 前抢救关键 memory)
- 新工具:`/memory-doctor`(自检 hook + jsonl + python 工具完整性)
- 新存储:从 JSONL 迁 SQLite 应对 10000+ 规模
- 新前端:WebUI 展示 memory 图谱(可视化 by_branch 关联)
- 新 agent 移植:把哲学搬到 Cursor / Aider / Cline
