# Memex 全局池 — 跨项目工作面

> **规范**:`~/.claude/MEMORY_SPEC.md`(v0.2)
> **索引**:`_index/{projects,branches,meta}.jsonl`
> **机制**:本文件由 Claude Code 的 `~/.claude/projects/<cwd>/memory/MEMORY.md` 通过 `@import` 自动加载,跨所有 cwd 共享。

---

## 项目速查

<!-- AUTO:START project-table -->
<!-- 此区块由 ~/.claude/bin/update_index_md.py 从 projects.jsonl 自动重生成 -->
<!-- AUTO:END project-table -->

## 全局纪律(feedback/)

> 用户硬性要求 — 跨项目的提交/分支/记忆/调试纪律。

<!-- AUTO:START feedback-list -->
<!-- 此区块由 update_index_md.py 自动重生成 -->
<!-- AUTO:END feedback-list -->

## 全局外部引用(reference/)

<!-- AUTO:START reference-list -->
<!-- 此区块由 update_index_md.py 自动重生成 -->
<!-- AUTO:END reference-list -->

## 集合层文档(global/*.md 顶层 + 子目录)

<!-- AUTO:START misc-list -->
<!-- 此区块由 update_index_md.py 自动重生成 -->
<!-- AUTO:END misc-list -->

## LRU / 淘汰策略

详见 `~/.claude/MEMORY_SPEC.md § 四`。`session-start-lru.sh` hook 启动时主动扫,有候选会提醒。
