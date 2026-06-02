# Roadmap

> 优先级:P0 必做 / P1 应做 / P2 想做 / P3 远期
> 欢迎在 issues 投票或提 PR。

## P0 — 已完成(v0.1 发布范围)

- [x] 5 个 event-listener hooks
- [x] 3 个 Python CLI 工具(rebuild_index / update_index_md / lru_compact)
- [x] JSONL 倒排索引(meta.jsonl + by_branch.jsonl)
- [x] status × decay LRU 状态机(active → dormant → candidate_to_delete)
- [x] 30d × 3 次压缩 + pinned 永不淘汰
- [x] 多 cwd 严格隔离 + monorepo 子项目支持
- [x] 失败兜底 ctx 闭环(never silent fail)
- [x] 傻瓜安装(install.sh)+ 安全卸载(uninstall.sh)
- [x] 中英双语 README + 5 篇 docs

## P1 — 下一个 milestone

- [ ] **`memory-doctor` 自检工具** — 自动检查 hook + jq + python3 + 索引一致性,给出修复建议
- [ ] **SessionStart hook 周期 LRU** — 每周第一次启动自动跑 `lru_compact.py`(目前手动)
- [ ] **`update_index_md.py` 自动跑** — 加 PostToolUse hook 在 memory 改后自动刷 INDEX.md
- [ ] **测试套件** — `tests/` 下端到端测试,CI 跑
- [ ] **更多 examples** — global / project overview / 多语言项目示例
- [ ] **CHANGELOG.md**
- [ ] **i18n docs** — 日语 / 韩语 / 西班牙语 README

## P2 — 想做

- [ ] **SQLite 后端**(应对 10000+ 规模)
  - 当前 JSONL 在 N=1000 时 jq 重写 ~150ms,N=10000 时秒级
  - 迁移路径:加 `~/.claude/bin/migrate_jsonl_to_sqlite.py`
- [ ] **WebUI dashboard**
  - 可视化 by_branch.jsonl 关联图谱
  - 时间线展示 last_access / decay 演化
- [ ] **Cursor 适配**
  - Cursor 有 [hook system](https://docs.cursor.com/hooks),可移植 7 个 hook
- [ ] **Aider 适配**
  - Aider 有 plugin system
- [ ] **VSCode 插件**
  - frontmatter LSP(自动补全 / 校验)
  - 工作面侧边栏(显示当前分支 memory)
- [ ] **`/memory-graph` 命令** — 生成 mermaid 图展示 `[[xxx]]` 关联

## P3 — 远期 / 探索

- [ ] **团队协作 feedback 同步**
  - `~/.claude/projects/<cwd>/memory/feedback/` 部分项的 git pull/push
- [ ] **Memory federation**(跨设备同步)
  - 加密同步 memory 到 S3 / iCloud / Dropbox
- [ ] **多模型支持**
  - GPT / Gemini / DeepSeek 等的 memory 视图
- [ ] **Memory diff & rollback**
  - 记 memory 历史版本,支持回滚
- [ ] **Reflection agent**
  - 借鉴 Stanford Generative Agents,定期反思 memory 提炼 meta-insights
- [ ] **Conversation replay**
  - 从 memory 重建过往会话上下文
- [ ] **Memory marketplace**
  - 共享 best-practice feedback(例:Go 工程纪律包、Python TDD 包)

## 贡献优先级

最容易上手的 PR:
1. P1 测试套件(Bash + Python pytest)
2. P1 examples 补充
3. P1 i18n docs(从中文 → 你的语言)
4. P2 Cursor / Aider 适配(分支可独立做)

## 不在 Roadmap

我们**故意不做**这些(违反核心哲学):
- ❌ 复杂 shell 解析(违反 spec § 七)
- ❌ "自动判断写什么 memory" 的 LLM 调用(违反 listener/handler 分工 — 这是 LLM 自己的事)
- ❌ 阻塞性 hook(违反 silent degrade 原则)
- ❌ memory 加密 / 权限管理(scope creep — 用文件系统层做)
