# CLI 工具用法(v0.2.2)

7 个 Python 工具,装到 `~/.claude/bin/`。

| 工具 | 一句话 |
|---|---|
| `derive_project_key.py` | git remote 归一化 + sha1[:12] → project_key,所有 hook 调它 |
| `update_memex_bridge.py` | 扫 cwd 子目录 git repo;维护 CLAUDE.md catalog manifest + MEMORY.md 指示性 bridge |
| **`memex_query.py`** | **LLM 按需查询入口**(v0.2.2 新增) |
| `rebuild_index.py` | 全量重建 3 个 jsonl 索引 |
| `update_index_md.py` | 从索引重写 INDEX.md 标记区块 |
| `lru_compact.py` | LRU 周扫 + 分支死亡检测 + decay/pin/rm 管理 |
| `migrate_v01_to_v02.py` | 从 v0.1 一次性迁移到 v0.2(YAML mapping 驱动) |

## 0. memex_query.py(v0.2.2)— LLM 按需查询入口

**作用**:取代 v0.2.1 把 INDEX 全量 @import 进 ctx 的做法。LLM 通过 Bash 主动调,按需拉具体内容。

```bash
# 列所有 active project(简洁清单)
python3 ~/.claude/bin/memex_query.py --list

# 看某 project 的元数据 + 分支 + feedback + reference
python3 ~/.claude/bin/memex_query.py --project <key>

# 拿某分支 memory 路径(找不到 → exit 1)
python3 ~/.claude/bin/memex_query.py --branch <key> <branch_slug>

# 列 feedback(可加 --project-filter / --term 过滤)
python3 ~/.claude/bin/memex_query.py --feedback
python3 ~/.claude/bin/memex_query.py --feedback --project-filter <key> --term redis

# 跨索引 grep
python3 ~/.claude/bin/memex_query.py --grep <term>

# 最近 N 天 access 过的
python3 ~/.claude/bin/memex_query.py --recent --days 7

# 索引完整性自检
python3 ~/.claude/bin/memex_query.py --health
```

**格式**:默认 markdown(给 LLM 直接读);`--json` 给脚本管道用。

**失败兜底**:未知 key/branch → stderr 错误 + exit 1。memex 根不存在 → exit 2。

---

---

## 1. derive_project_key.py

**作用**:把一个 git repo 路径派生成 `(project_key, display_name, origin, origin_aliases)`。**单一身份来源**,所有 hook 调它。

```bash
# 单 repo,出 JSON
python3 ~/.claude/bin/derive_project_key.py /path/to/repo

# 扫 parent 下所有 git repo,出表
python3 ~/.claude/bin/derive_project_key.py --scan ~/code --table

# 只跑 URL 归一化(调试用)
python3 ~/.claude/bin/derive_project_key.py --normalize "git@github.com:org/x.git"
# → github.com/org/x
```

**派生规则**:
```
有 origin:    sha1(normalize(origin))[:12] + "-" + basename(repo_root)
无 origin:    sha1(abspath(repo_root))[:12]  + "-" + basename(repo_root)
非 git repo:  is_git=false,无 key
```

**归一化**:strip 协议(`git@`/`https://`/`ssh://`)、strip `.git`、strip 尾斜杠 → `github.com/org/repo`。

---

## 2. update_memex_bridge.py

**作用**(v0.2.1):bootstrap hook 的核心。主模式:扫 cwd 子目录 + 包含 recently-active 项目维护 bridge + 维护 `~/.claude/CLAUDE.md` 的 catalog 块。`--touch` 模式:hook 触发用,快速 bump `last_access`。

### 主模式

```bash
python3 ~/.claude/bin/update_memex_bridge.py --cwd <path> [--memex <path>] [--cc-memory <path>]
```

输出 JSON 含:
- `discovered_repos`:cwd 扫到几个 git repo
- `cwd_active_keys`:cwd 内有内容的 project
- `recent_active_keys`:cwd 外但 `last_access < MEMEX_RECENT_DAYS` 的有内容 project
- `active_imported_keys`:两者合并,bridge 真正 @import 的
- `bridge_action`:`created` / `replaced` / `appended` / `unchanged`
- `catalog_action`:`created` / `replaced` / `appended` / `unchanged` / `skipped`(opt-out)

### --touch 模式(hook 用)

```bash
python3 ~/.claude/bin/update_memex_bridge.py --touch <project_key> [--repo <path>] [--memex <path>]
```

快速 bump `projects.jsonl.last_access` 为 now。若 key 不在 jsonl 且 `--repo` 派生的 key 跟传入匹配 → 自动新建一条。**hook 触发时后台异步跑**,不阻塞。

**何时手动跑(主模式)**:bootstrap 没自动触发想强刷;或调试看哪些 repo 被识别。

### env vars / opt-out

- `MEMEX_RECENT_DAYS=30`:recently-active 窗口
- 跳过 catalog 维护(任一即生效):
  - `export MEMEX_NO_CATALOG=1`(shell env,临时)
  - `touch ~/.claude/memex/.no_catalog`(sentinel 文件,持久,跨 shell)

---

## 3. rebuild_index.py

**作用**:全量重建 `~/.claude/memex/_index/{meta,branches,projects}.jsonl`。LRU 字段(last_access / decay / status)从旧 meta 保留。

```bash
# 默认扫 ~/.claude/memex
python3 ~/.claude/bin/rebuild_index.py

# 指定根
python3 ~/.claude/bin/rebuild_index.py --memex /path/to/memex

# 不动 projects.jsonl(只重 meta + branches)
python3 ~/.claude/bin/rebuild_index.py --no-rewrite-projects
```

**何时手动跑**:
- jsonl 损坏(`jq . meta.jsonl` 报错)
- 手动加 .md 后 hook 没自动入索引
- 大规模改 frontmatter 后

**输出**:
```
✅ rebuild_index 完成:
   · meta.jsonl       55 行
   · branches.jsonl   7 行
   · projects.jsonl   4 项(更新 branch_count)
```

---

## 4. update_index_md.py

**作用**:从 jsonl 重写 `memex/global/INDEX.md` 和每个 `memex/projects/<key>/INDEX.md` 里的 `<!-- AUTO:START ... -->` 标记区块。

```bash
# 全跑
python3 ~/.claude/bin/update_index_md.py

# 只跑 global/INDEX.md
python3 ~/.claude/bin/update_index_md.py --global

# 只跑某 project
python3 ~/.claude/bin/update_index_md.py --project 8f92ec49d8b1-example-service
```

**区块**:
- global/INDEX.md:`project-table`(项目速查)、`feedback-list`、`reference-list`、`misc-list`
- projects/<key>/INDEX.md:`branch-list`、`project-docs`、`project-feedback`、`project-reference`

标记缺失/损坏 → 区块跳过(不破坏原 INDEX.md)。

---

## 5. lru_compact.py

**作用**:LRU 周扫 + 压缩候选清单 + 分支死亡检测 + decay/pin/rm 管理。

### 5a. 扫描清单(默认行为)

```bash
python3 ~/.claude/bin/lru_compact.py
# 或指定根:
python3 ~/.claude/bin/lru_compact.py --memex /path/to/memex
```

输出按 4 阶段分组:`pending_compact_1/2/3`、`pending_delete`、`awaiting_user_authorize_delete`。

### 5b. quiet 模式(hook 用)

```bash
python3 ~/.claude/bin/lru_compact.py --quiet
# 输出:
#   compact_1:N
#   compact_2:N
#   compact_3:N
#   pending_delete:N
#   awaiting_delete:N
```

`session-start-lru.sh` 用这个判断是否有候选。

### 5c. 标 decay(LLM 压缩完调用)

```bash
python3 ~/.claude/bin/lru_compact.py --mark projects/<key>/old.md 1
# → decay=1, status=dormant, size 重算
```

### 5d. 锁定永不淘汰

```bash
python3 ~/.claude/bin/lru_compact.py --pin projects/<key>/critical.md
python3 ~/.claude/bin/lru_compact.py --unpin projects/<key>/critical.md
```

### 5e. 检测分支死亡

```bash
# 对某项目 + 其 repo 路径对账
python3 ~/.claude/bin/lru_compact.py --detect-deleted-branches <project_key> <repo_path>
```

逻辑:`git for-each-ref refs/heads refs/remotes` × `branches.jsonl[project_key=k]` → 本地+远程都查不到的标 `status=dormant`。

### 5f. 显式删除(三层闸门)

```bash
python3 ~/.claude/bin/lru_compact.py --rm projects/<key>/branches/<slug>.md
# 闸门:
#   1. status 必须 candidate_to_delete(除非 --force)
#   2. last_access 必须 ≥ 60 天
#   3. dump 前 10 行让你看
#   4. 软删到 _trash/<UTC>_<basename>
#   5. 从 jsonl 移除
```

### 自定义周期

```bash
export MEMEX_LRU_PERIOD_DAYS=60
python3 ~/.claude/bin/lru_compact.py
```

---

## 6. migrate_v01_to_v02.py

**作用**:从 v0.1 一次性迁移到 v0.2。YAML mapping 驱动。

```bash
# dry-run 看 plan
python3 ~/.claude/bin/migrate_v01_to_v02.py \
  --source ~/.claude/projects/<your-old-cwd-slug>/memory \
  --mapping ~/my-mapping.yaml

# apply
python3 ~/.claude/bin/migrate_v01_to_v02.py \
  --source ~/.claude/projects/<your-old-cwd-slug>/memory \
  --mapping ~/my-mapping.yaml --apply
```

mapping.yaml 写每个 `<biz>` 目录对应哪个 git repo;详见 [examples/migrate-mapping.example.yaml](../examples/migrate-mapping.example.yaml)。

**特点**:
- copy 不 move:旧池一字不动,等 LRU 30d × 3 次自然回收
- 写前备份 `~/.claude/memex.pre-apply-backup-<ts>/`
- 重入幂等(基于 sha256 对比)

---

## 综合工作流

### 月底 LRU 维护

```bash
# 1. 检测各项目已删分支(逐项目)
for key in $(jq -r '.key' ~/.claude/memex/_index/projects.jsonl); do
  repo=$(jq -r --arg k "$key" 'select(.key==$k) | .repo_paths_seen[0]' ~/.claude/memex/_index/projects.jsonl)
  [ -n "$repo" ] && python3 ~/.claude/bin/lru_compact.py --detect-deleted-branches "$key" "$repo"
done

# 2. 扫候选清单
python3 ~/.claude/bin/lru_compact.py

# 3. 把清单交给 Claude:"按 spec § 四.A 压缩这些"
#    Claude 逐条 Read → 写紧凑版 → 跑 --mark <path> <decay>

# 4. 刷 INDEX.md
python3 ~/.claude/bin/update_index_md.py
```

### memory 系统坏掉的修复

```bash
# 1. 备份(memex.pre-apply-backup-<ts> 已有,但建议再 cp 一份)
cp -a ~/.claude/memex ~/.claude/memex.recovery-$(date +%s)

# 2. 全量重建索引
python3 ~/.claude/bin/rebuild_index.py

# 3. 刷新 INDEX.md
python3 ~/.claude/bin/update_index_md.py
```

### 测试 hook 行为

**注意**:macOS bash 可能启了 `xpg_echo`,**用 `printf '%s'` 替代 `echo`** 测试 hook 输出,避免 JSON 里的 `\n` 字面被解成真换行:

```bash
printf '%s' '{"tool_input":{"command":"git -C ~/repo checkout feat/X"},"tool_response":{"exitCode":0}}' \
  | bash ~/.claude/hooks/post-checkout-handoff.sh \
  | jq -r '.hookSpecificOutput.additionalContext'
```
