# Contributing to harness-memex

欢迎扩展!这个项目刻意保持小而精,**质量大于功能**。

## 提 issue 之前

- 看 [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) 有没有已知答案
- 装的最新版吗(`git pull`)
- 重启 Claude Code 试过吗

## 提 PR 之前

### 硬纪律(违反 = 关 PR)

1. **脚本不解析复杂 shell**(`MEMORY_SPEC.md § 七`)
   - hook 只支持 `cd <path>; git ...` / `git -C <path> ...` 两种最简形式
   - 想加 pushd / subshell / 别名 / env var 解析?**关 PR**。让 LLM 兜底。

2. **失败永远塞 ctx,不允许 silent fail**
   - hook 解析失败 → 通过 `hookSpecificOutput.additionalContext` 抛 ⚠️ ctx
   - LLM 必须能看到 hook 试过又失败了

3. **harness 七原则**(`MEMORY_SPEC.md § 七`)
   - 单一职责 / 幂等 / 零状态 / 可观测 / 可降级 / 可演进 / 可回滚 / 隔离 / 兜底闭环

4. **JSONL atomic write**
   - 任何改 jsonl 必须 tmpfile + os.replace(Python)或 tmpfile + mv(Bash)
   - 不允许直接覆盖写

5. **按 project-key(git origin)隔离,所有 hook 调 `derive_project_key.py`**
   - 防同名分支串(`MEMORY_SPEC.md § 十`)
   - 不要在 hook 里自己 hash origin / 自己解析 git-common-dir,用单一来源工具

### 哲学(强烈推荐)

- **静态规则脚本管,动态判断 LLM 管**
- 不重复造轮子:Anthropic / Linux kernel / Redis / Nginx 已经踩过的坑,直接学
- 小而精 > 大而全

## 加新 hook 的 checklist

- [ ] 在 `hooks/` 加 `<your-hook>.sh`
- [ ] shebang `#!/bin/bash`,失败 `exit 0`(保护性除外)
- [ ] 输入从 stdin 读 JSON,用 `jq -r '.tool_input.xxx // ""'`
- [ ] 输出用 `jq -nc --arg c "$ctx" '{hookSpecificOutput:{...}}'`
- [ ] 失败兜底:塞 ⚠️ ctx,不静默
- [ ] 在 `templates/memex-hooks.json` 加注册片段
- [ ] 在 `docs/HOOKS.md` 加说明段
- [ ] 加端到端测试到 `tests/`(如果有)

## 加新 CLI 工具的 checklist

- [ ] 在 `bin/` 加 `<your-tool>.py`
- [ ] shebang `#!/usr/bin/env python3`
- [ ] 写 jsonl 用 `tempfile + os.replace` 原子
- [ ] 默认 memex 根:`HOME / ".claude/memex"`,加 `--memex <path>` flag 让用户覆盖
- [ ] 在 `docs/CLI.md` 加用法
- [ ] 工具帮助文本(`python3 tool.py --help` 或顶部注释)

## 加新 docs / examples 的 checklist

- [ ] 不带任何具体公司 / 项目 / 服务名 / 凭证
- [ ] 例子用 `example-project` / `feat/<date>/example-feature` 这种泛化
- [ ] 中英文都更新(README 双语,docs 可以中文,examples 双语优先)

## Commit 规范

格式:`<type>: <description>`,type 用 conventional commits:
- `feat:` 新功能
- `fix:` bug 修复
- `docs:` 文档
- `refactor:` 重构
- `test:` 测试
- `chore:` 杂项

例子:
```
feat: add lru_compact --restore for un-compaction
fix: bootstrap drift detection ignored macOS resource forks
docs: add troubleshooting for jq path issues
```

## 测试

**注意**:macOS bash 可能启了 `xpg_echo`,会把字面 `\n` 解成真换行,破坏 JSON 传给下游。**用 `printf '%s'` 替代 `echo`**:

```bash
# 手动测某个 hook(用 printf 而非 echo)
printf '%s' '{"tool_input":{"command":"git -C ~/repo checkout feat/X"},"tool_response":{"exitCode":0}}' \
  | bash hooks/post-checkout-handoff.sh

# 测 Python 工具
python3 bin/rebuild_index.py --memex /tmp/test-memex
```

## Code of Conduct

Be kind. Critique code, not people. 不容忍 harassment / discrimination。

## 许可

提 PR 即同意你的贡献按 [MIT License](./LICENSE) 发布。
