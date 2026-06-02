# 跟 Claude Code Auto Memory 协作

> Memex 不替代 Auto Memory,是它的 **branch-aware extension pack**。

## Claude Code Auto Memory 是什么(v2.1.59+ 起内置)

[官方文档](https://code.claude.com/docs/en/memory):

- Claude 自己读自己写 `~/.claude/projects/<cwd-slug>/memory/MEMORY.md`
- session 启动时加载 MEMORY.md 前 200 行 / 25KB
- 默认开,可关:`autoMemoryEnabled: false` 或 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- `/memory` slash command 打开管理

**关键事实**:这是 Anthropic 官方做的,跨 session 自动学习用户偏好,**已经覆盖 memory 系统 80% 需求**。

## Auto Memory 的 4 个明确空白(Memex 补)

[Anthropic 文档原话](https://code.claude.com/docs/en/memory):

> "All worktrees and subdirectories of a project share the same memory directory."

意思:**Auto Memory 是 cwd 级,不切分支**。这是文档明写的设计选择,不是 bug。

Memex 补这 4 件:

| # | Auto Memory 不做 | Memex 怎么补 |
|---|---|---|
| 1 | 分支级 memory 切换 | `post-checkout-handoff.sh` PostToolUse 检测切完成,塞 ctx 让 LLM 并行 Write a + Read b |
| 2 | 结构化 schema(JSONL 索引 / decay 字段) | `_index/meta.jsonl` + `by_branch.jsonl` 倒排,jq O(1) 查 |
| 3 | 显式 LRU 30d × 3 次压缩 + pinned + 软删 | `lru_compact.py` + `session-start-lru.sh` 主动触发 |
| 4 | 保护分支提交守卫 + monorepo 子项目分支识别 | `check-protected-branch.sh` 拦 commit/push + `cd <subdir>` / `git -C <subdir>` 解析 |

## 协作机制(关键!)

bootstrap hook 每次跑都判断 `MEMORY.md` 状态,**不抢 Anthropic 的资源**:

```
状态机:
  a) MEMORY.md 不存在        → 软链 MEMORY.md → INDEX.md(Memex 当入口)
  b) MEMORY.md 是软链(我们建的) → 不动
  c) MEMORY.md 是真文件(Auto Memory 写的) → 末尾追加 @INDEX.md(幂等)
```

**c 的具体效果**:

```markdown
# MEMORY.md(Auto Memory 写的原内容)
用户偏好 Go 1.21
项目用 PostgreSQL
... ...

<!-- Memex extension —— 由 ~/.claude/hooks/session-bootstrap.sh 自动追加 -->
@INDEX.md
```

`@INDEX.md` 是 Claude Code 原生的 `@import` 语法 — Auto Memory 加载 MEMORY.md 时会自动递归拉 INDEX.md(以及 INDEX.md 里 `@` 的其它文件)进 user message。

**所以**:
- Auto Memory 写 MEMORY.md → 自动 + 我们结构 → 全部进 Claude 上下文
- 我们的 INDEX.md / feedback / reference / branch memory 通过 `@import` 被 Auto Memory 拉进上下文
- **零冲突 / 零抢资源 / 零侵入**

## 用户场景

### 场景 A:你之前没用过 Auto Memory

- bootstrap 第一次跑,`MEMORY.md` 不存在
- 软链 MEMORY.md → INDEX.md
- Memex 当主入口

### 场景 B:你之前一直用 Auto Memory(开了一阵子)

- bootstrap 跑,`MEMORY.md` 是 Auto Memory 写的真文件
- 末尾追加 `@INDEX.md`
- Auto Memory 继续管它,Memex 通过 `@import` 把结构注入

### 场景 C:你之前关了 Auto Memory(`autoMemoryEnabled: false`)

- 跟场景 A 一样,Memex 当主入口

### 场景 D:你之前用 Memex,**后来又开 Auto Memory**

- Auto Memory 启动后自动写入 MEMORY.md(覆盖我们的软链)
- 下次 Claude session 启动,bootstrap 检测到 MEMORY.md 不再是软链了
- **自动转入场景 B 模式**:追加 `@INDEX.md`
- 无缝切换,不丢东西

## 配置建议

| 想要 | 怎么配 |
|---|---|
| Auto Memory + Memex 都用(推荐) | 不动 settings,装 Memex 即可 |
| 只用 Memex | `export CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`(然后装 Memex)|
| 只用 Auto Memory | 不装 Memex(显然)|

## 检验自己装得对不对

```bash
# 1. 看 MEMORY.md 内容
cat ~/.claude/projects/$(pwd | sed 's#/#-#g')/memory/MEMORY.md

# 期望两种之一:
# 场景 A/C:是软链 → INDEX.md
# 场景 B/D:Auto Memory 内容 + 末尾 @INDEX.md

# 2. 看 hook 注册
jq '.hooks.PreToolUse[].hooks[].command | select(test("memex|memory"))' ~/.claude/settings.json
```
