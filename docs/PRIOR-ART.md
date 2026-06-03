# Prior Art — Memex 不是孤军奋战

> 这个生态位上,Anthropic 自己做了 80%,社区已经有几个尝试做剩下的 20%。
> Memex 是其中之一,**不是首发**。

## Anthropic 自己做的(根基)

| 功能 | 来源 |
|---|---|
| Auto Memory(自动写 MEMORY.md)| Claude Code v2.1.59+ 内置 |
| CLAUDE.md 分层加载 | [docs](https://code.claude.com/docs/en/memory) |
| `@import` 递归加载 | 同上 |
| 30+ hook events | [docs](https://code.claude.com/docs/en/hooks) |
| `.claude/rules/` + paths frontmatter | [docs](https://code.claude.com/docs/en/settings) |
| Session JSONL + `/resume` + checkpoint | [docs](https://code.claude.com/docs/en/sessions) |
| Subagent persistent memory | [docs](https://code.claude.com/docs/en/sub-agents) |

**这是 80%**。如果你只需要"跨 session 自动学习用户偏好",**直接用 Auto Memory,不需要 Memex**。

## 社区里跟 Memex 类似的项目

### 1. [`Davidcreador/claude-code-branch-memory-manager`](https://github.com/Davidcreador/claude-code-branch-memory-manager)

**做什么**:跟 Memex 最像 — 切 git 分支时切换 memory。
**做法**:用 git post-checkout hook(不是 Claude Code hook)+ 每个分支一个独立 CLAUDE.md。
**跟 Memex 差异**:
- 用 git hook 而不是 Claude Code hook → 不在 Claude 内
- 没有 JSONL schema / 索引
- 没有 LRU 压缩
- 没有保护分支拦截
- 没有跨 cwd 隔离矩阵

**适合谁**:简单场景 — 单 cwd,单 git repo,只需要分支切 memory。

### 2. [`coleam00/claude-memory-compiler`](https://github.com/coleam00/claude-memory-compiler)

**做什么**:把多个 markdown 笔记编译成一个 CLAUDE.md(类似 build 系统)。
**跟 Memex 差异**:
- 偏"编译时" 工具,不是"运行时" hook
- 不感知 git 分支
- 不感知 session 事件

**适合谁**:有自己的笔记系统想推进 Claude 上下文。

### 3. [`codenamev/claude_memory`](https://github.com/codenamev/claude_memory)

**做什么**:Ruby gem,提供 memory 管理 CLI。
**跟 Memex 差异**:
- Ruby 依赖
- 没有 hook 集成

**适合谁**:Ruby 生态用户。

## 学术 / 思想源头(不是直接竞品,但是灵感来源)

| 项目 | 价值 |
|---|---|
| [**Letta / MemGPT**](https://arxiv.org/abs/2310.08560)(Packer et al. 2023)| "LLM as Operating System with tiered memory" — 我们的 status × decay 状态机受其影响 |
| [**Voyager**](https://voyager.minedojo.org/)(NVIDIA Jim Fan)| Minecraft 长跑 agent skill library — 启发"按分支分库"思路 |
| [**Generative Agents**](https://arxiv.org/abs/2304.03442)(Stanford Park et al. 2023)| memory stream + reflection — 未来 P3 路线 |
| Andrej Karpathy "LLM OS" 概念 | hook + jsonl = OS scheduler + file metadata |

## Memex 在这个生态位的位置

```
┌──────────────────────────────────────────────────┐
│  Anthropic Claude Code(80%)                      │
│  - Auto Memory / CLAUDE.md / @import / hooks     │
└──────────────────────────────────────────────────┘
                       ↑ 用 @import 协作
┌──────────────────────────────────────────────────┐
│  Memex(补 20%):                                  │
│  - 分支级 memory 切换                              │
│  - JSONL schema + 倒排索引                         │
│  - 显式 LRU + 软删保护                             │
│  - 保护分支守卫 + monorepo 子项目识别              │
└──────────────────────────────────────────────────┘
                       ↕ 同生态位
  Davidcreador/branch-memory-manager  ← 只切分支
  coleam00/memory-compiler             ← 只编译
  codenamev/claude_memory              ← Ruby CLI
```

## 为什么 Memex 仍然值得开源

**唯一独有的事**:
1. 跟 Auto Memory 协作(在 `MEMORY.md` 末尾幂等追加 `<!-- memex:bridge -->` 块 + `@import`,不抢写权)
2. **按 git origin 派生 project-key 隔离**:同 Claude 进程内**多项目 × 多分支**矩阵,跨 worktree / 跨 cwd / 跨启动位置一致(绕过 Claude Code [issue #39920](https://github.com/anthropics/claude-code/issues/39920))
3. monorepo / workspace 子项目分支识别(`cd <subdir>` / `git -C` 解析)
4. 显式 LRU 状态机 + 60d 防误删 + 软删 `_trash/`
5. 失败兜底 ctx 闭环(silent degrade 但不 silent fail)
6. 中英双语 + 5+ 篇 docs + 端到端测试 + 一键安装

但**不是**:
- "重新发明 memory" — Anthropic 做了根基
- "Claude memory 终极方案" — 还有很多空间
- "替代 CLAUDE.md / Auto Memory" — 完全互补

## 引用其它项目

如果你想换/补:
- **想简单点** → `Davidcreador/claude-code-branch-memory-manager`(纯 git hook)
- **想编译式** → `coleam00/claude-memory-compiler`
- **Ruby 生态** → `codenamev/claude_memory`
- **学术深度** → [MemGPT](https://github.com/letta-ai/letta)

Memex 不打压它们,各取所长。
