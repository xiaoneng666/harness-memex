# Examples

四类 memory 各举一个例子,**全部虚构**。

| 文件 | 类型 | 演示什么 |
|---|---|---|
| [feedback-example.md](./feedback-example.md) | feedback | 用户硬性纪律的写法(Why + How to apply + 反例)|
| [reference-example.md](./reference-example.md) | reference | 外部系统引用(地址 + 用法 + 边界)|
| [branch-memory-example.md](./branch-memory-example.md) | branch | 分支独立工作面(进度 + 决策 + 踩坑 + 链接)|

## 共同结构

所有 memory 都用 YAML frontmatter:

```yaml
---
name: <kebab-case-slug>
description: <一句话摘要,索引里展示用>
metadata:
  type: feedback | reference | user | global | project | branch
---
```

## 文件命名

- feedback / reference / user / global:`<slug>.md`(扁平)
- project 维度:`projects/<business>/<slug>.md`
- branch 维度:`projects/<business>/branches/<branch_slug>.md`
  - 其中 `<branch_slug>` 是 `branch_name.replace('/', '_').replace('-', '_')`
  - 如 `feat/<date>/oauth-login` → `feat_0531_oauth_login.md`

## 内部链接

memory 间用 `[[name-slug]]` 互引(不是 markdown 链接,是符号链接):
```markdown
关联 [[example-feedback-conventional-commits]] [[example-reference-monitoring-dashboards]]
```

未来工具会扫这些 `[[...]]` 自动构建关联图谱(P2 roadmap)。

## 自己加 example

欢迎 PR 加你的领域 example(纯虚构,不带任何真实公司/项目)。一些想法:
- `feedback-tdd.md` — TDD 流程的硬纪律
- `reference-internal-api-catalog.md` — 内部 API 目录
- `project-overview-microservices.md` — 微服务架构 overview
- `global-tech-stack.md` — 通用技术栈速查
