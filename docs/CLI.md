# CLI 工具用法

3 个 Python 工具,装到 `~/.claude/bin/`。可以独立调用,也由 hook 自动调用。

## 1. rebuild_index.py

**作用**:全量重建 `_index/meta.jsonl` 和 `_index/by_branch.jsonl`,LRU 字段保留。

```bash
# 重建当前 cwd 对应的 memory 索引
python3 ~/.claude/bin/rebuild_index.py

# 指定 mem_root
python3 ~/.claude/bin/rebuild_index.py /path/to/memory
```

**何时手动跑**:
- jsonl 损坏(`jq . meta.jsonl` 报错)
- 手动加 .md 后 hook 没自动入索引(post-write-memory-sync 挂了)
- 整体 frontmatter 大改后

**输出示例**:
```
  · 读旧 meta.jsonl: 48 条
  · 扫描 .md: 48 条
  · 保留 last_access(LRU 不重置): 48 条
  · 新 last_access(用 mtime 兜底): 0 条
  · 写 meta.jsonl: 48 行
  · 写 by_branch.jsonl: 5 行
✅ rebuild 完成: /path/to/memory/_index/meta.jsonl
```

---

## 2. update_index_md.py

**作用**:从 `meta.jsonl` 自动重写 `INDEX.md` 里的 AUTO 标记区块。

支持 3 个区块:
- `project-table` — projects/* 的项目速查表(分 `<biz>` / `<biz>/<sub>` / `<biz>/<sub>/branches` 三档)
- `feedback-list` — feedback/*.md 的速查链接(用 · 分隔)
- `reference-list` — reference/*.md 的速查链接(带 description)

```bash
# 重写当前 cwd 的 INDEX.md
python3 ~/.claude/bin/update_index_md.py

# 指定 mem_root
python3 ~/.claude/bin/update_index_md.py /path/to/memory
```

**何时手动跑**:加完一批 memory 后,想刷新 INDEX.md 项目速查表

**AUTO 标记**:`INDEX.md` 里要有:
```markdown
<!-- AUTO:START project-table -->
<!-- 此区块由 update_index_md.py 自动重生成 -->
... 现有内容 ...
<!-- AUTO:END project-table -->
```

标记缺失 → 直接 abort 不写(不破坏原有 INDEX.md)。

---

## 3. lru_compact.py

**作用**:LRU 周扫 + 压缩候选清单 + 分支删除检测 + decay 字段维护。

### 3a. 扫描清单(默认行为)

```bash
python3 ~/.claude/bin/lru_compact.py
```

**输出示例**:
```
# LRU 周扫报告 — /Users/x/.claude/projects/-Users-x-project-myapp/memory
# 周期 30d × 3 次压缩 + 候选删除
# 总 memory 条目: 48

## 待第 1 次压缩 (decay 0→1, 30d 未 access) — 5 条
   动作: ≤ 2KB · 保留 Why/决策/状态/链接
   · projects/myapp/old_design.md  (5.2KB, 45d 未 access)
       架构 v1 已被 v2 替代...
   · ...
```

### 3b. 标 decay(LLM 压缩完调用)

```bash
# 单条:把某 memory 标为已压缩 1 次
python3 ~/.claude/bin/lru_compact.py --mark projects/myapp/old_design.md 1
# → r['decay']=1, r['status']='dormant', r['size'] 重算

# 标 decay=0:回到 active
python3 ~/.claude/bin/lru_compact.py --mark projects/myapp/old_design.md 0
```

### 3c. 锁定永不淘汰

```bash
# pin: 标 status=pinned(永不进 LRU,即使一年没 access)
python3 ~/.claude/bin/lru_compact.py --pin projects/myapp/critical.md

# unpin: 回 active
python3 ~/.claude/bin/lru_compact.py --unpin projects/myapp/critical.md
```

**典型用例**:开发中的活跃分支 memory,用户不希望被自动压缩

### 3d. 检测分支删除

```bash
# 在 git 仓库根跑
python3 ~/.claude/bin/lru_compact.py --detect-deleted-branches /path/to/repo
```

**逻辑**:
- 拿仓库所有本地 + 远程分支
- 对所有 `type=branch` 的 memory:若分支在本地+远程都查不到 → 标 `status=dormant` 进 LRU

### 自定义周期

```bash
# 改成 60 天周期
export MEMEX_LRU_PERIOD_DAYS=60
python3 ~/.claude/bin/lru_compact.py
```

---

## 综合工作流

### 月底 LRU 维护

```bash
# 1. 检测已删分支,标 dormant 进 LRU
python3 ~/.claude/bin/lru_compact.py --detect-deleted-branches /path/to/repo

# 2. 扫候选清单
python3 ~/.claude/bin/lru_compact.py

# 3. 把清单交给 Claude:"按 spec § 三.A 压缩这些"
#    Claude 逐条 Read → 写紧凑版 → 跑 --mark <path> <decay>

# 4. 刷新 INDEX.md
python3 ~/.claude/bin/update_index_md.py
```

### memory 系统坏掉的修复

```bash
# 1. 备份
cp -r ~/.claude/projects/<slug>/memory ~/.claude/projects/<slug>/memory.backup-$(date +%s)

# 2. 全量重建索引
python3 ~/.claude/bin/rebuild_index.py

# 3. 刷新 INDEX.md
python3 ~/.claude/bin/update_index_md.py
```

### 加新 memory 后

通常 `post-write-memory-sync.sh` hook 会自动入索引。手动场景:

```bash
# 手动加了 .md(没经过 Claude Write)
python3 ~/.claude/bin/rebuild_index.py
```
