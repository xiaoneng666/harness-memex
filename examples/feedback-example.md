---
name: example-feedback-conventional-commits
description: 例:用户要求 commit message 遵循 conventional commits 规范
metadata:
  type: feedback
---

# 用户纪律:Conventional Commits

**Why**:团队约定 commit message 用 conventional commits 规范,方便 CHANGELOG 自动生成 + 关联 semantic versioning。

**How to apply**:
- Claude 写 commit message 时遵循:`<type>(<scope>?): <description>`
- type ∈ `feat / fix / docs / style / refactor / test / chore / perf / ci`
- scope 可选,如 `feat(auth): add OAuth2 login flow`
- 单 commit 单一变更主题

**示例**:
```
✅ feat(payment): add Stripe webhook handler
✅ fix(api): handle empty user_id in /v2/profile
✅ refactor(db): extract repository pattern from service layer

❌ update stuff  ← 太泛
❌ fix bug      ← 不知道哪个 bug
❌ Add new feature for users.    ← 句号 + 大写 + 没 type
```

**反例**:Claude 写出 `add login feature` → 用户会要求改成 `feat(auth): add OAuth2 login`。

关联:[[example-feedback-signal-only]] [[example-reference-git-workflow]]
