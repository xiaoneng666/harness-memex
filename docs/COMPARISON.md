# 跟其它 memory 方案对比

> **Memex 不重复造轮子。它填补的是"工程化的、可跨分支跨 cwd 的长期工作面"这块空白。**

## 一图速览

| 维度 | Claude Code 自带<br>CLAUDE.md + `/resume` | ChatGPT Memory | Cursor Memory | MemGPT / Letta | **Memex** |
|---|---|---|---|---|---|
| 跨 session 持久化 | ✓ 项目根 CLAUDE.md | ✓ 全局 | 部分 | ✓ | ✓ |
| **分支感知**(切分支自动收档+启档) | ❌ | ❌ | ❌ | ❌ | **✓** |
| **项目隔离**(按 git origin,跨 cwd/worktree 一致) | ❌ | ❌ | ❌ | ❌ | **✓** |
| **同 session 内多项目并行** | ❌ | ❌ | ❌ | ❌ | **✓** |
| 自动维护(无需手动改) | ❌(要你改 CLAUDE.md)| 部分 | 部分 | ✓ | ✓ |
| 结构化分类(6 类) | ❌ 一坨 markdown | ❌ | ❌ | tiered memory | **✓** feedback/reference/user/global/project/branch |
| 索引查询 | grep | 向量(语义)| 向量 | tiered paging | **✓** JSONL O(1) jq 命中 |
| LRU 淘汰(防 context bloat) | ❌ | ❌ 静默丢 | ❌ | ✓ tiered | **✓** 30d × 3 次压缩 + pinned |
| 事件驱动(git/Read/Write 触发)| ❌ | ❌ | ❌ | ❌ | **✓** 7 hooks |
| 失败兜底(LLM 自动接管)| N/A | N/A | N/A | N/A | **✓** |
| 开源 + 可拓展 | ❌ 闭源 | ❌ 闭源 | ❌ 闭源 | ✓ | ✓ MIT |
| 零锁定(都是 .md + .jsonl)| ✓ | ❌ | ❌ | ❌ | ✓ |

## 逐项对比

### 1. Claude Code 自带的 CLAUDE.md + `/resume`

**Anthropic 官方提供的方案**(无需安装,开箱即用):
- 项目根 `CLAUDE.md`:每次自动加载,放项目元信息(技术栈、架构、代码约定)
- 全局 `~/.claude/CLAUDE.md`:跨项目共享的个人偏好
- `/resume`:接续最近一次 session
- Claude Code 4.x 起,system prompt 注入自动 memory

**做得好的**:
- 零配置,装 Claude Code 就有
- CLAUDE.md 是 plain markdown,可读可改
- 跟 Claude 系统集成深(不会被 truncate)

**Memex 解决的痛点**:
| Claude 自带做不到 | Memex 怎么做 |
|---|---|
| CLAUDE.md 是一坨,**没分类**(混了纪律/参考/分支/决策)| 6 类 frontmatter type 严格分工 |
| 不会按分支变化(切分支后 CLAUDE.md 还是同一份)| `post-checkout-handoff.sh` 切分支自动让 LLM 并行写 from + 读 to 分支 memory |
| 不会按 cwd 子项目变化(monorepo 下子项目分支 hook 抓不到)| 按 git origin 派生 project-key,跨 cwd/worktree 一致 |
| `/resume` 只接续最近一次,跨数十 session 不顶 | jsonl 索引 + LRU 让数百条 memory 不爆 |
| 没有"自动维护"概念(要你手动改)| 7 个 hook 把事件转译成自动维护动作 |
| 没有自动压缩(老决策跟新决策一起占 context)| 30d × 3 次自动压缩到骨架 |

**结论**:**Memex 跟 CLAUDE.md 不冲突,完全互补**。
- `CLAUDE.md`:项目元信息(架构、技术栈)— 静态,几乎不变
- `Memex`:动态工作面(分支进度、决策演化、纪律累积)— 持续累积

---

### 2. ChatGPT Memory(OpenAI)

**做法**:服务端维护一份"用户全局 memory",每次对话自动注入。

**做得好的**:
- 全设备同步
- 自动从对话学习用户偏好

**不适合用于编程工作流的原因**:
- ❌ 一份全局 memory,**不区分项目**
- ❌ 闭源,只能 ChatGPT 用
- ❌ 没有分支 / 工作面概念
- ❌ 服务端黑盒,你不知道存了啥,删了啥

**Memex 怎么补**:
- 按 project-key(git origin)隔离 memory,worktree / 多 cwd 启动都一致
- 全部本地 .md + .jsonl,你完全控制

---

### 3. Cursor Composer Memory

**做法**:Cursor IDE 内置的 memory,跨文件夹追踪上下文。

**做得好的**:
- IDE 内嵌,UI 体验好

**不适合长跑项目的原因**:
- ❌ 闭源,锁定 Cursor
- ❌ 没有分支感知(切 git 分支不会自动切 memory)
- ❌ 没有结构化分类
- ❌ 没有压缩策略

**Memex 怎么补**:
- 开源,跨工具未来可移植
- 6 类结构 + LRU 状态机

---

### 4. MemGPT / Letta(开源,LLM OS 论文)

**做法**:把 LLM 当 OS,memory 分 main context / external context / paging,有 tiered storage。

**学术上做得很好**:
- 首次提出 "LLM OS with memory hierarchy"(Packer et al. 2023)
- tiered memory + recall mechanism

**不适合直接拿来用 Claude Code 的原因**:
- ❌ 是个独立 framework,要重新搭 agent
- ❌ 跟 Claude Code hook 系统不集成
- ❌ 没有分支感知

**Memex 跟 MemGPT 的关系**:
- MemGPT 提供了 tiered memory 的**思想**;我们的 status × decay 状态机受其启发
- 但 Memex **专门为 Claude Code 工作流设计**,不重做 framework

---

### 5. 自己手写 .md memory(很多人在做)

**做法**:在 `~/notes/<project>.md` 或 `<repo>/docs/` 写笔记。

**做得好的**:
- 零依赖,完全自由
- markdown 文件未来不锁定

**累的地方**:
- ❌ 你要**手动维护**每个文件
- ❌ Claude 不会自动 Read 你的笔记(你要在 prompt 里说"读 X.md")
- ❌ 多了就找不到
- ❌ 没有时间维度(哪条最近用 / 哪条很久没碰)

**Memex 怎么补**:
- 文件位置标准化(`~/.claude/memex/projects/<project-key>/`)
- hook 自动注入对应分支 memory 进 Claude ctx
- jsonl 索引让查询 O(1)
- LRU 自动清理

---

## 一句话总结

> **Claude Code 自带的 memory 是"开箱即用",ChatGPT Memory 是"被动学习",MemGPT 是"学术框架",Memex 是"专门为 Claude Code 长跑开发工作流设计的工程化方案"。**

它们不互斥。Memex 跟 CLAUDE.md 配合用最佳:
- CLAUDE.md 放静态项目元信息
- Memex 管动态工作面 + 按 project-key 跨 cwd / worktree 隔离


---

## Prior Art — 这个生态位上其它项目

详细对比:[PRIOR-ART.md](./PRIOR-ART.md)

简表:
- [`Davidcreador/claude-code-branch-memory-manager`](https://github.com/Davidcreador/claude-code-branch-memory-manager) — 跟 Memex 最像,纯 git hook 切分支
- [`coleam00/claude-memory-compiler`](https://github.com/coleam00/claude-memory-compiler) — 编译式 CLAUDE.md
- [`codenamev/claude_memory`](https://github.com/codenamev/claude_memory) — Ruby gem

Memex 跟它们的差异:
1. 跟 **Auto Memory 协作**(在 MEMORY.md 末尾追加 `<!-- memex:bridge -->` 块 + `@import`,不抢写权)
2. 按 **git origin 派生 project-key** 隔离,worktree / monorepo / 多 cwd 启动都一致(绕过 [issue #39920](https://github.com/anthropics/claude-code/issues/39920))
3. 同 Claude 进程内**多项目 × 多分支**矩阵(其它都是单 cwd / 单 repo)
4. 显式 LRU 30d×3 + 60d 防误删 + 软删 `_trash/`
5. 失败兜底 ctx 闭环
