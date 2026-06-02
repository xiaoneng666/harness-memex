# Memory Index — 本 cwd 工作面

> 本文件由 `~/.claude/hooks/session-bootstrap.sh` 从模板初始化。**首次 bootstrap 后由 LLM 按需扩展。**
>
> **全局 Memory 规范**:`~/.claude/MEMORY_SPEC.md`(三层结构 / JSONL schema / LRU / hook 行为)
> **机器索引**:`_index/meta.jsonl`(LRU)、`_index/by_branch.jsonl`(分支倒排)
> **查询例**:`jq 'select(.branch=="feat/<date>/example")' _index/by_branch.jsonl`

---

## 目录结构(标准三层 — 自动建,LLM 直接用)

```
.
├── INDEX.md                          ← 本文件
├── MEMORY.md                         ← 软链接 → INDEX.md
├── _index/                           ← 机器索引
│   ├── meta.jsonl
│   └── by_branch.jsonl
├── feedback/                         本 cwd 范围的纪律/反馈
├── reference/                        外部系统引用
├── user/                             用户画像
├── global/                           跨业务项目的项目级文档
└── projects/                         业务工作面 memory
    └── <project>/
        ├── overview.md
        ├── *.md
        └── branches/
            └── <branch_slug>.md
```

## 项目速查

<!-- AUTO:START project-table -->
<!-- 此区块由 ~/.claude/bin/update_index_md.py 自动重生成,扫 _index/meta.jsonl -->

(空 — `python3 ~/.claude/bin/update_index_md.py` 跑过就会自动填充)

<!-- AUTO:END project-table -->

## 反馈 / 纪律(feedback/)

> 用户硬性要求 — 提交/分支/记忆/调试纪律。任何会话开干前应扫一眼。

<!-- AUTO:START feedback-list -->
<!-- 此区块由 update_index_md.py 自动重生成 -->

(空)

<!-- AUTO:END feedback-list -->

## 外部引用(reference/)

<!-- AUTO:START reference-list -->
<!-- 此区块由 update_index_md.py 自动重生成 -->

(空)

<!-- AUTO:END reference-list -->

## LRU / 淘汰策略(详见 `~/.claude/MEMORY_SPEC.md` § 三)

| `decay` | `status` | 触发 | 动作 |
|---|---|---|---|
| 0 | active | — | 不动 |
| 0 | dormant(30d 未访问) | LRU 周扫 | 第 1 次压缩 → decay→1 |
| 1 | dormant(再 30d) | LRU 周扫 | 第 2 次压缩 → decay→2 |
| 2 | dormant(再 30d) | LRU 周扫 | 第 3 次压缩 → decay→3 |
| 3 | dormant(再 30d) | LRU 周扫 | 标 candidate_to_delete,**通知用户** |
| 3 | candidate_to_delete | **用户授权** | rm + 移除索引 |
| - | pinned | 用户显式锁 | 永不淘汰 |

**分支删除规则**:本地远程都查不到的分支 → 该分支 memory 立即 `status=dormant` 进 LRU 流程。

**last_access 更新规则**:`pre-read-memory-bump.sh` 在每次 Read memory/**/*.md 时自动更新 jsonl。

**新加/修改 memory 自动入索引**:`post-write-memory-sync.sh` 在 Write/Edit memory/**/*.md 后自动增量同步 jsonl。
