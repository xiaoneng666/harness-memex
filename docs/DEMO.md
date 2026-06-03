# 5 分钟 Demo — 跟着跑一遍

> 装完 `install.sh` 后,跟着这个流程跑一遍,体验完整能力。

## 准备

- 装好 Memex(`./install.sh` 完成)
- **重启 Claude Code**
- 准备两个项目目录(模拟多项目场景)
  ```bash
  mkdir -p ~/demo/{proj-a,proj-b}
  cd ~/demo/proj-a && git init -q && touch README.md && git add . && git commit -qm "init"
  cd ~/demo/proj-b && git init -q && touch README.md && git add . && git commit -qm "init"
  ```

---

## 场景 1 — 自动 bootstrap

```bash
cd ~/demo/proj-a
claude  # 启动 Claude Code
```

**在 Claude 里**:
```
> 跑一个 ls
```

**期望**:
- Claude 跑 ls
- 你看到 system message:`✨ Memex v0.2 初始化完成 (~/.claude/memex/)。识别到本 cwd 下 N 个 git repo。INDEX 已搭桥...`
- 跑 `ls ~/.claude/memex/` 看到 `_index/  global/  projects/` 三层骨架
- 跑 `python3 ~/.claude/bin/derive_project_key.py ~/demo/proj-a` 看到 `{"key": "<hash>-proj-a", ...}`

---

## 场景 2 — 写一条 feedback,自动入索引

**在 Claude 里**:
```
> 记一条:本项目用 Go 1.21,所有错误用 fmt.Errorf 包,不用 panic
```

**期望**:
- Claude 决定这条是项目专属(只对 proj-a),Write 到 `~/.claude/memex/projects/<key-A>/feedback/go-error-handling.md`
- (或决定是全局纪律,Write 到 `~/.claude/memex/global/feedback/go-error-handling.md`)
- `post-write-memory-sync.sh` hook 触发,stderr 显示 `[date] post-write-memory-sync: ...` + 自动跑 rebuild + 刷对应 INDEX.md
- 跑 `grep go-error-handling ~/.claude/memex/_index/meta.jsonl`,看到这条记录

---

## 场景 3 — 切分支自动收档+启档

**先建两个分支**:
```bash
cd ~/demo/proj-a
git checkout -b feat/<date>/login
echo "login" > login.go && git add . && git commit -qm "feat: login skeleton"
git checkout -b feat/<date>/profile
echo "profile" > profile.go && git add . && git commit -qm "feat: profile skeleton"
```

**在 Claude 里**(假设当前 feat/<date>/profile):
```
> 在 memory 里记一条:profile 用 OAuth 拉头像,storage 走 S3
```

Claude 会建 `~/.claude/memex/projects/<key-A>/branches/feat_<date>_profile.md`。

**切回 feat/<date>/login**:
```
> 跑 cd ~/demo/proj-a && git checkout feat/<date>/login
```

**期望**:
- `post-checkout-handoff.sh` hook 触发(PostToolUse,checkout 已成功)
- 你看到 ctx 注入(via system message):
  - 🔄 切分支完成(proj-a): feat/<date>/profile → feat/<date>/login
  - 立刻并行处理(无依赖,可同时发):
    - Write `~/.claude/memex/projects/<key-A>/branches/feat_<date>_profile.md`(收档)
    - Read `~/.claude/memex/projects/<key-A>/INDEX.md`(启档,目标分支没 memory 时看项目门面)
- Claude 同回合并行发 Write + Read 两个 tool call,立即知道现在在 login 分支

---

## 场景 4 — 同一 Claude session,切到另一个项目 + 分支

**在同一个 Claude session 里**:
```
> cd ~/demo/proj-b
> 跑 git checkout -b feat/<date>/api-refactor
> 在 memory 记: proj-b 用 gRPC + protobuf,接口在 api/v2/ 下
```

Claude 会自动:
- 当前 cwd 仍是 ~/demo/proj-a,bootstrap 没新跑(同 session 同 cwd 已 marker)
- **但 proj-b 是不同 git repo,有自己的 project-key**
- post-write 时 hook 自动按文件路径下的 project_key 维护索引

**切回 proj-a**:
```
> cd ~/demo/proj-a
> 跑 git checkout feat/<date>/login
```

**期望**:
- `post-checkout-handoff.sh` 用 proj-a 的 project_key 查 `branches.jsonl`,命中 proj-a 的 feat/<date>/login memory(如果有)
- **proj-b 的 memory 完全不串过来** — 因为查询是按 `(project_key_A, branch)` 二维
- Claude 知道现在在 proj-a 而不是 proj-b

> **这就是杀手锏特性**:**按 project-key(git origin)隔离**,同 Claude 进程内 N 项目 × M 分支矩阵。同名分支跨 repo 不会串。

---

## 场景 5 — Read feedback 自动续命(防 LRU 误杀)

```bash
# 看 feedback 当前 last_access
grep go-error-handling ~/.claude/memex/_index/meta.jsonl
```

**在 Claude 里**:
```
> 看一下我之前关于 Go 错误处理的 feedback
```

Claude 会 Read 那个文件。

```bash
# 复查 last_access
grep go-error-handling ~/.claude/memex/_index/meta.jsonl
```

**期望**:`last_access` 时间戳已经更新到刚才。这是 `pre-read-memory-bump.sh` hook 干的。

> **作用**:30 天后 LRU 扫的时候,这条仍 active,不会被压缩。read-heavy 的 feedback 永远活着。

---

## 场景 6 — LRU 扫描

```bash
python3 ~/.claude/bin/lru_compact.py
```

**期望**(因为刚装,所有 memory 都 < 30d):
```
# LRU 周扫报告 — ...
# 总 memory 条目: 3
✅ 无待压缩 / 候选删除 — 全部 active 或 pinned
```

**模拟 30d 后**:
```bash
# 把某条 memory 的 last_access 改成 40 天前(模拟)
MEMEX="$HOME/.claude/memex"
python3 -c "
import json
with open('$MEMEX/_index/meta.jsonl') as f:
    lines = [json.loads(l) for l in f if l.strip()]
for r in lines:
    if 'profile' in r['path']:
        r['last_access'] = '2025-04-23T00:00:00Z'
with open('$MEMEX/_index/meta.jsonl', 'w') as f:
    for r in lines:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
"

# 复扫
python3 ~/.claude/bin/lru_compact.py
```

**期望**:
```
## 待第 1 次压缩 (decay 0→1, 30d 未 access) — 1 条
   动作: ≤ 2KB · 保留 Why/决策/状态/链接
   · projects/<key>/branches/feat_<date>_profile.md  (X B, 40d 未 access)
       <description>

---
压缩流程(LLM 决策):见 ~/.claude/MEMORY_SPEC.md § 四.A
```

**让 Claude 压缩**:
```
> 按 spec § 四.A 把 LRU 扫到的这条压缩到 ≤ 2KB
```

Claude 会 Read + Write 紧凑版,然后跑 `lru_compact.py --mark` 更新 decay。

---

## 场景 7 — 保护分支拦截

```
> 跑 cd ~/demo/proj-a && git checkout main && git commit --allow-empty -m "test"
```

**期望**:hook **exit 2 拦截**,你看到:
```
❌ 当前在保护分支 [main],禁止直接 commit/push。
   功能分支:git checkout -b feat/<date>/<name>
   修复分支:git checkout -b bugfix/<date>/<name>
```

**改保护分支列表**:
```bash
export MEMEX_PROTECTED_BRANCHES="main master develop"  # 移除 production
```

再试:`git commit` 到 production 不再拦截。

---

## 清理 demo

```bash
rm -rf ~/demo
# memex 池里的 proj-a / proj-b 项目骨架(若想清):
PROJ_A_KEY=$(python3 ~/.claude/bin/derive_project_key.py ~/demo/proj-a 2>/dev/null | jq -r .key)
PROJ_B_KEY=$(python3 ~/.claude/bin/derive_project_key.py ~/demo/proj-b 2>/dev/null | jq -r .key)
rm -rf ~/.claude/memex/projects/${PROJ_A_KEY} ~/.claude/memex/projects/${PROJ_B_KEY}
python3 ~/.claude/bin/rebuild_index.py  # 重建索引
```

---

## 下一步

- 用到自己的项目里:`cd <你的项目>` + 启动 Claude Code,自动 bootstrap
- 看 [docs/HOOKS.md](./HOOKS.md) 了解每个 hook 细节
- 看 [docs/CLI.md](./CLI.md) 了解 3 个工具用法
- 看 [docs/COMPARISON.md](./COMPARISON.md) 了解跟 Claude 自带 / 其它方案的差异
