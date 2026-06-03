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

> "Per repository, shared across worktrees" (Auto Memory 是 **per-repo,worktree 共享**)

但 [issue #39920](https://github.com/anthropics/claude-code/issues/39920):Auto Memory 用 `git-common-dir` 派生 slug,**worktree 实际上全部映射到主 worktree**,且**不切分支**。

Memex 补这 4 件:

| # | Auto Memory 不做 | Memex 怎么补 |
|---|---|---|
| 1 | 分支级 memory 切换 | `post-checkout-handoff.sh` PostToolUse 检测切完成,塞 ctx 让 LLM 并行 Write a + Read b |
| 2 | 结构化 schema(JSONL 索引 / decay 字段) | `_index/{projects,branches,meta}.jsonl` 三重倒排,jq O(1) 查 |
| 3 | 显式 LRU 30d × 3 次压缩 + pinned + 软删 | `lru_compact.py` + `session-start-lru.sh` 主动触发 |
| 4 | worktree / monorepo / 多 cwd 启动一致 | 按 `git remote get-url origin` 归一化 + sha1[:12] 派生 **project-key**,绕过 git-common-dir bug |

## 协作机制(关键!)

bootstrap hook 在 Claude Code per-cwd `MEMORY.md` 末尾**幂等追加** `<!-- memex:bridge -->` 区块,**不抢 Anthropic 写权**:

```
状态机(对 ~/.claude/projects/<cc-slug>/memory/MEMORY.md):
  a) 文件不存在       → 新建,内容 = bridge 块
  b) 文件存在但无 bridge → 末尾追加 bridge 块
  c) 文件存在含 bridge   → 正则替换 bridge 块(幂等)
```

**bridge 块的内容**:

```markdown
# MEMORY.md 内 Auto Memory 写的原内容(我们不动)
用户偏好 Go 1.21
项目用 PostgreSQL
... ...

<!-- memex:bridge:start -->
<!-- 由 ~/.claude/hooks/session-bootstrap.sh (Memex v0.2) 自动维护,勿手改 -->
@~/.claude/memex/global/INDEX.md
@~/.claude/memex/projects/<key-A>/INDEX.md
@~/.claude/memex/projects/<key-B>/INDEX.md
<!-- memex:bridge:end -->
```

`@<path>` 是 Claude Code 原生的 `@import` 语法 — Auto Memory 加载 MEMORY.md 时会自动递归拉对应 INDEX.md(最多 4 hops)进 user message。

**bridge 块只 @import "有内容"的 project**(`projects/<key>/` 下除 INDEX.md 外有 .md),避免数十个空 stub 塞 ctx。

**所以**:
- Auto Memory 写 MEMORY.md → 我们的 bridge 块 + Auto Memory 内容 → 全部进 Claude 上下文
- 我们的 global + per-project INDEX.md 通过 `@import` 被 Auto Memory 拉进上下文
- **零冲突 / 零抢资源 / 零侵入**

## 用户场景

### 场景 A:你之前没用过 Auto Memory

- bootstrap 第一次跑,`MEMORY.md` 不存在
- 新建 `MEMORY.md`,内容只含 `<!-- memex:bridge -->` 块
- Auto Memory 启用时自己写入,内容会追加在 bridge 之前

### 场景 B:你之前一直用 Auto Memory

- bootstrap 跑,`MEMORY.md` 是 Auto Memory 写的真文件
- 末尾幂等追加 `<!-- memex:bridge -->` 块
- Auto Memory 继续管它,Memex 通过 `@import` 把结构注入

### 场景 C:你之前关了 Auto Memory(`autoMemoryEnabled: false`)

- 跟场景 A 一样,但 MEMORY.md 永远只有 bridge 块

### 场景 D:cwd 子目录有新 git repo 加入

- bootstrap 检测到新 project_key → 建 `projects/<key>/INDEX.md` 骨架
- bridge 块下次 session 加这一行 `@.../projects/<key>/INDEX.md`(若该 project 已有内容)
- 完全无感

## 配置建议

| 想要 | 怎么配 |
|---|---|
| Auto Memory + Memex 都用(推荐) | 不动 settings,装 Memex 即可 |
| 只用 Memex | `export CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`(然后装 Memex)|
| 只用 Auto Memory | 不装 Memex(显然)|

## 检验自己装得对不对

```bash
# 1. 看 MEMORY.md 末尾有 bridge 块
sed -n '/memex:bridge:start/,/memex:bridge:end/p' \
  ~/.claude/projects/$(pwd | sed 's#/#-#g')/memory/MEMORY.md

# 2. 看 memex 全局池骨架在
ls ~/.claude/memex/_index/  # 应有 projects.jsonl branches.jsonl meta.jsonl

# 3. 看 hook 注册
jq '.hooks.PreToolUse[].hooks[].command | select(test("memex|memory"))' ~/.claude/settings.json
```
