# 故障排查

## 安装后 hook 没生效

**现象**:新 cwd 启动 Claude,跑命令后 `~/.claude/projects/<slug>/memory/` 没自动建出来。

**排查**:
1. `cat ~/.claude/settings.json | jq '.hooks.PreToolUse[].hooks[].command'` 看有没有 memex 相关
2. 没有 → 重跑 `install.sh`
3. 有但还是不工作 → **重启 Claude Code**(settings.json 改完要重启)
4. 还不工作 → 看 `cat ~/.claude/projects/<slug>/.../session-log` 找 hook 错误

## hook 执行报错

**现象**:Claude Code 显示 hook error。

**排查**:
1. `command -v jq python3 git` 三个都得有
2. `bash ~/.claude/hooks/<hook>.sh` 手动跑,看错在哪
3. 装个 mock stdin 测:`echo '{"tool_input":{"command":"ls"}}' | bash ~/.claude/hooks/check-protected-branch.sh`
4. 临时禁:`mv ~/.claude/hooks ~/.claude/hooks.disabled`

## memory 文件改了但索引没更新

**现象**:`grep '_new_file' ~/.claude/projects/<slug>/memory/_index/meta.jsonl` 找不到。

**排查**:
1. 看 hook stderr 有没有 `[date] post-write-memory-sync: ...` 这行
2. 没有 → `post-write-memory-sync.sh` 没触发或 file_path 路径模式不匹配
3. 手动同步:`python3 ~/.claude/bin/rebuild_index.py`
4. 看 hook 跑没跑通:`tail -20 ~/Library/Logs/claude-code/*.log`(macOS)

## jsonl 损坏

**现象**:`jq . meta.jsonl` 报 parse error。

**修复**:
```bash
# 备份
cp ~/.claude/projects/<slug>/memory/_index/meta.jsonl{,.bak-$(date +%s)}

# 全量重建(LRU 字段会从备份读,但损坏行的 LRU 数据丢失)
python3 ~/.claude/bin/rebuild_index.py
```

## INDEX.md 跟实际不一致

**现象**:`INDEX.md` 里项目速查表少了新加的 memory。

**修复**:
```bash
python3 ~/.claude/bin/update_index_md.py
```

如果 AUTO 标记缺失或损坏,工具会报错 abort。手动加回标记:
```markdown
<!-- AUTO:START project-table -->
... 任何旧内容 ...
<!-- AUTO:END project-table -->
```

## 多项目同名分支 memory 串了

**现象**:project A 切 `feat/X`,看到 project B 的 `feat/X` memory。

**检查**(v0.2):
1. `python3 ~/.claude/bin/derive_project_key.py <repoA>` 和 `<repoB>` 看 key 是否不同
2. 不同则 `branches.jsonl` 里两条独立,不该串。`jq -c 'select(.branch_slug=="feat_X")' ~/.claude/memex/_index/branches.jsonl` 看
3. 若 key 相同,可能两 repo 共享同一 origin(罕见)→ 用 `repo_paths_seen` 区分,或手动改 origin

## monorepo / workspace 子项目分支 hook 不识别

**现象**:Claude cwd=`~/project/monorepo`(不是 git 仓库根),用户跑 `cd subapp && git checkout feat/X`,hook 没识别。

**已支持**(spec § 七 两种最简形式):
- `cd <path> && git ...`
- `git -C <path> ...`

**确认**(注意:测试时用 `printf '%s'` 而非 `echo`,避免 bash xpg_echo 把 `\n` 字面解成真换行,破坏 JSON):
```bash
printf '%s' '{"tool_input":{"command":"cd subapp && git checkout feat/X"},"tool_response":{"exitCode":0}}' \
  | bash ~/.claude/hooks/post-checkout-handoff.sh
# 应该看到 ctx 注入,含 project_key 路径
```

不工作 → 检查 `subapp/.git` 在不在 / `feat/X` 分支真存在不存在 / `derive_project_key.py <subapp>` 返不返 key。

## LRU 扫不到任何候选

**现象**:`python3 ~/.claude/bin/lru_compact.py` 总显示 `✅ 无待压缩`。

**正常**:所有 memory `last_access < 30d` 时确实没候选。

**异常排查**:
1. `cat ~/.claude/projects/<slug>/memory/_index/meta.jsonl | jq -r '.last_access' | sort | head`
   - 看最早的 last_access 时间
2. 如果某条很久没 access 但还是 active → 检查它有没有被 pin
   - `cat ... | jq 'select(.status=="pinned")'`

## 保护分支拦截太严了

**现象**:你想在 `staging` 分支直接 commit,但被拦了。

**改**:
```bash
# 自定义保护分支(覆盖默认 main master develop production)
export MEMEX_PROTECTED_BRANCHES="main master production"
# 加到 ~/.zshrc 让永久生效
```

## 卸载后想恢复 memory

**现象**:跑了 `uninstall.sh`,后悔了。

**修复**:memory 文件本身没删,在 `~/.claude/projects/*/memory/`。重跑 `install.sh` 即可恢复 hook + 工具,memory 文件无缝接续。

## 上报 bug / 求助

1. 提供:`hostname` / `claude --version` / `jq --version` / `python3 --version` / OS
2. 复现步骤
3. hook stderr 输出
4. 提 [issue](https://github.com/<your-fork>/harness-memex/issues)
