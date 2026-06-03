# FAQ — 常见问题

## 安装 & 兼容

### Q: 跟 Claude Code 自带的 CLAUDE.md 冲突吗?
**A**:不冲突,**完全互补**。CLAUDE.md 放项目静态元信息,Memex 管动态工作面。两个都装,各取所长。详见 [COMPARISON.md](./COMPARISON.md)。

### Q: 会影响 Claude Code 性能吗?
**A**:几乎无感。
- hook 平均 < 50ms / 次
- post-write-sync 全量 reindex 在 N=50 条时约 30ms
- LRU 扫是手动跑,不影响日常

### Q: 会增加 Claude 的 token 消耗吗?
**A**:**平均略减少**。
- ✅ 减少:每次新 session 不用重新解释项目(原来 5-10 分钟 prompt 不再需要)
- ✅ 减少:切分支自动注入 memory,不用 LLM 自己去 Read 多个文件查
- ❌ 增加:hook ctx 注入(每次平均 200-500 tokens)
- **净效果**:省下"重新解释"的成本远超 ctx 注入

### Q: 卸载后 memory 数据丢吗?
**A**:不丢。`uninstall.sh` 只删 hooks + 工具 + settings.json 注册,**所有 memory 数据保留在 `~/.claude/projects/*/memory/`**。重装 `install.sh` 立即接续。

### Q: 必须用 Claude Code 吗?Cursor / Aider 能用吗?
**A**:**目前只支持 Claude Code**(基于其 hook API)。理论上可以适配 Cursor / Aider / Cline(它们都有 hook 或 plugin 系统),欢迎贡献。

### Q: 支持 Windows 吗?
**A**:hook 是 bash 脚本,理论上要 WSL / Git Bash。**目前测试覆盖 macOS + Linux**,Windows 欢迎报告 + 贡献。

---

## 使用 & 工作流

### Q: 同一个 Claude session 里能切多个项目吗?
**A**:**能,这是核心亮点**。
- 同 session 内你可以:cwd A 工作 → cd B → cd A → cwd C
- v0.2:bootstrap 把 cwd 下所有 git repo 的 INDEX 都 `@import` 到 MEMORY.md
- 切分支时按 `git origin` 派生的 project-key 命中各自的分支记忆 — **同名分支跨 repo 不会串**

### Q: 同一个 cwd 里切多个分支会串吗?
**A**:不会。`branches.jsonl` 按 `(project_key, branch_slug)` 二维倒排,jq O(1) 命中目标分支记忆。切分支时 `post-checkout-handoff.sh` 自动收档 from + 启档 to。

### Q: monorepo / workspace 下子项目分支怎么办?
**A**:**v0.2 天然支持**。hook 解析 `cd <subdir> && git ...` / `git -C <subdir> ...` 两种最简形式,从子项目 git repo 派生 project-key,完全独立。worktree 也走通(不再被 Claude Code [issue #39920](https://github.com/anthropics/claude-code/issues/39920) 影响)。复杂 shell(pushd / 别名 / subshell)失败时 hook 塞 ⚠️ ctx 让 LLM 接管。

### Q: 跟向量检索 RAG 比怎样?
**A**:**不同的设计目标**。
- 向量 RAG:语义检索海量非结构化文档,答用户问题
- Memex:结构化的工作面 memory,自动维护 + 自动注入 ctx
- 可以共存:Memex 管"我的工作面",RAG 管"项目文档库"

### Q: 团队怎么协作?memory 能共享吗?
**A**:**memory 默认是个人的**(在 `~/.claude/` 下)。如果想团队共享:
- **共享 feedback**:把 `feedback/` 软链到一个 git repo,团队 PR
- **共享 reference**:同上
- **branch memory 不建议共享**:它反映个人开发上下文,共享会污染

### Q: memory 怎么备份?
**A**:`~/.claude/projects/*/memory/` 里全是 plain markdown + jsonl。`git init` 推个人仓库即可。或定期 `tar -czf` 到云盘。

### Q: Claude 写错 memory 怎么办?
**A**:就是改 markdown 文件,改完 `post-write-memory-sync.sh` hook 自动重 reindex。或者手动:
```bash
python3 ~/.claude/bin/rebuild_index.py
```

---

## 设计 & 哲学

### Q: 为啥用 JSONL 不是 SQLite?
**A**:轻量 + LLM 可读 + 零注入风险 + 千级规模够用。SQLite 是杀鸡用牛刀。规模到 10000+ 再考虑迁移。详见 [ARCHITECTURE.md 决策 1](./ARCHITECTURE.md)。

### Q: 为啥 30 天 × 3 次压缩,不是直接删?
**A**:memory 是"关键 Why / 架构决策",直接删会丢史。3 次压缩让内容从"流水账"逐步退化成"骨架",**关键 Why 永远保留**。120 天保护期足够发现误删。

### Q: 为啥 hook 不解析复杂 shell?
**A**:这是**刻进 spec 的硬纪律**。shell 命令无限,加 case 是无底洞。**静态规则归脚本,动态判断归 LLM**。失败时塞 ⚠️ ctx 让 LLM 接管。详见 [ARCHITECTURE.md 决策 5](./ARCHITECTURE.md)。

### Q: 为啥 hook 失败要塞 ctx 不是 silent exit 0?
**A**:silent exit 0 = LLM 不知道脚本失败 = 不会接管 = memory 系统静默坏掉。塞 ⚠️ ctx 让 LLM 立即知道"我没识别,你自己看"。这是真正的 listener/handler 闭环。

---

## 故障 & 安全

### Q: hook 死循环 / 误拦怎么办?
**A**:临时禁:
```bash
mv ~/.claude/hooks ~/.claude/hooks.disabled
```
排查完恢复:`mv ~/.claude/hooks.disabled ~/.claude/hooks`。

### Q: settings.json 改错了怎么恢复?
**A**:`install.sh` 改 settings 前必备份(`*.memex-backup-<timestamp>`)。`cp` 回来即可。

### Q: memory 文件存的是隐私吗?可以 git push 吗?
**A**:**Claude 默认会按 spec 第四节"只记 Why / 决策 / 状态",不记 diff / 凭证**。但你要**自己负责审 memory 内容**,push 个人 repo 前 grep 一遍 secrets。

### Q: memory 加密吗?
**A**:**不加密**(plain markdown)。如果含敏感信息,文件系统层加密(macOS FileVault / Linux LUKS)。

---

## 演进 & 贡献

### Q: 下一步会做啥?
**A**:见 [ROADMAP.md](./ROADMAP.md)。

### Q: 怎么贡献?
**A**:见 [CONTRIBUTING.md](../CONTRIBUTING.md)。**特别欢迎**:
- 移植到其它 AI coding agent(Cursor / Aider / Cline)
- 新 hook / 新工具
- 多语言文档(目前中英双语)
- 实际使用反馈

### Q: 有 Slack / Discord 吗?
**A**:暂时没有。issue / PR 即可。如果用户多了,会建社区。

---

没找到答案?[开 issue](https://github.com/xiaoneng666/harness-memex/issues) 或贡献到 FAQ。
