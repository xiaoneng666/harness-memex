---
name: example-branch-feat-0531-oauth-login
description: 例:feat/0531/oauth-login 分支独立工作面 — 进度/思路/状态/链接
metadata:
  type: branch
---

# feat/0531/oauth-login 工作面

> 路径:`projects/example-project/branches/feat_0531_oauth_login.md`
> 涉及仓库:`<example-project>` · 分支:`feat/0531/oauth-login`

## 目标

支持用户用 Google / GitHub OAuth2 登录,替代纯密码登录。

## 进度

- [x] 调研:决定用 [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) 还是自己实现 → **自己实现**(用 `golang.org/x/oauth2`)
- [x] DB schema:`user_oauth_link` 表(user_id, provider, provider_uid, access_token, refresh_token, expires_at)
- [x] Backend:`/auth/oauth/{provider}/start` 和 `/callback` 路由 + state 校验防 CSRF
- [ ] Frontend:登录页加 "Sign in with Google/GitHub" 按钮
- [ ] Test:E2E 跑通 Google 登录流(staging 环境)
- [ ] Docs:更新 onboarding README

## 关键决策

1. **state 用 JWT 不用 session**:无状态后端,scaling 简单。HMAC 签 user_intent + timestamp,callback 校验。
2. **refresh_token 加密存**:用 KMS 信封加密,DB 里只存密文。
3. **provider_uid 是主键的一部分**:`(provider, provider_uid)` 联合唯一,允许同一邮箱挂多个 provider。

## 踩过的坑

- ❌ 一开始用 random session ID 校验 state → 重启服务后所有进行中的 OAuth flow 失败。换成 JWT 后无状态。
- ❌ Google 的 `id_token` claims 里 email 可能为空(用户没授权 email scope)→ 必须先校验 scope 包含 `email`。

## 下一步

1. Frontend 加按钮(待 design 团队 review)
2. 跑 staging E2E
3. 灰度 5% 流量看错误率

## 链接

- 设计文档:`projects/example-project/oauth-design-v2.md`
- 关联 feedback:[[example-feedback-conventional-commits]]
- 关联 reference:[[example-reference-monitoring-dashboards]]
