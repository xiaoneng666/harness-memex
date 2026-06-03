---
name: example-feedback-companion-repo-branches
description: 例:写分支 memory 时必须显式列出本次迭代里配合开发的其他仓库分支,让跨仓库联动全貌一眼可见
metadata:
  type: feedback
---

# 用户纪律:分支 memory 必须列「配合开发的其他仓库分支」

**Why**:一次业务需求经常跨 2~9 个仓库联动(如某 backend 重构 = `service-a` RPC 改造 + `bff-x` 透传调整 + `service-b` 拦截层加;某契约迁移 = 4 仓同步发版)。**只看单仓分支 memory 会丢失跨仓全貌** — 新会话切到任一仓的分支后,不知道这次还动了哪些其他仓的哪些分支,容易遗漏一起拉 / 一起合 develop / 一起部署。

配合 `[[example-feedback-branch-naming-consistency]]`(跨仓同名分支)和 `[[example-feedback-report-repos-after-each-change]]`(改后报仓)形成闭环。

**How to apply**:

1. **新建分支 memory 时**:即使本次只动了一个仓,也要写"## 配合开发的其他仓库分支"段(标 `_(none)_` 也行)— 给"是否单仓"一个明确答案
2. **更新分支 memory 时**:期间增加了新仓联动 → 本段追加;某仓本期实际未改动 → 从表里删掉(对齐「实际有改动」边界)
3. **链接 memory**:用 `[[name]]` 链向对方仓的分支 memory(`name:` slug);允许暂未立档的悬空链接(标记后续要写)
4. **关系一句话**:< 20 字,只写关系类型;详情让 reader 跳对方 memory,**避免两边重复**
5. **双向链接**:确认配合关系时,两边 memory 都要互相登记(不要单向),让任一仓切入都能见全貌

---

**格式**:

```markdown
## 配合开发的其他仓库分支

| 仓库 | 分支 | 关系 | memory |
|---|---|---|---|
| **<repo>** | `<branch>` | <短标签> | [[<对方分支 memory slug>]] |

仅本仓:_(none)_ 或留空即可。
```

**关系列**只用最短的话标"是什么关系"。常见值:
- `联动 RPC` — 本仓调对方仓提供的接口
- `同期独立` — 同期上线但两仓接口独立
- `BFF 透传` — BFF 层只透传,无业务逻辑
- `前后端契约` — 前后端同改一个接口
- `数据迁移配合` — schema / 数据双仓同步

需要细节 → 点 `[[...]]` 跳对方 memory。

---

## 示例(脱敏)

某迭代 `feat/<date>/example-quota-redesign` 在仓 `service-a` 的分支 memory 包含:

```markdown
## 配合开发的其他仓库分支

| 仓库 | 分支 | 关系 | memory |
|---|---|---|---|
| **bff-x** | `feat/<date>/example-quota-redesign` | BFF 透传新 RPC | [[example-bff-x-feat-quota]] |
| **service-b** | `feat/<date>/example-quota-redesign` | 联动 RPC(被 service-a 调)| [[example-service-b-feat-quota]] |
| **frontend-app** | `feat/<date>/example-quota-redesign` | 前后端契约(新错误码)| [[example-frontend-app-feat-quota]] |
```

LLM 切到 `service-b` 的同名分支看 memory 时,立刻知道还有 service-a / bff-x / frontend-app 一起改;切到 `bff-x` 时同样。

---

## 反例

❌ 「分支 memory 只写本仓改动,完全不提其他仓」→ 新会话切到对方仓不知道有联动,部署时漏发版
❌ 「关系列写一大段描述对方仓职责」→ 双仓重复维护,改一个忘改另一个
❌ 「单向链接(只 A 仓提 B 仓,B 仓不提 A 仓)」→ 切到 B 仓时丢全貌

关联:[[example-feedback-branch-naming-consistency]] [[example-feedback-report-repos-after-each-change]] [[example-branch-memory-example]]
