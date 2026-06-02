# Memex

> **Branch-aware extension pack for Claude Code Auto Memory**
> Named after Vannevar Bush's 1945 *Memex* concept.

> **Does not replace** Anthropic Auto Memory (built-in since v2.1.59+, covers ~80%).
> **Adds 4 things Auto Memory does not do**: ① per-branch memory ② JSONL schema index ③ explicit LRU + soft-delete ④ protected-branch guard + monorepo subproject support.

Turn one-shot Claude Code sessions into a **cross-session, cross-branch, cross-cwd long-term workspace** that accumulates over time.

[中文 README](./README.md) · [Architecture](./docs/ARCHITECTURE.md) · [Motivation](./docs/MOTIVATION.md) · [Quick install](#-install-in-3-steps)

---

## ⚡ 30-second pitch

| Before (vanilla Claude Code) | After (with Memex) |
|---|---|
| Re-explain project context every new session | LLM auto-loads INDEX + index summary for this cwd |
| Forget where you left off when switching branches | Branch checkout auto-saves current + auto-loads target (memory injected into ctx) |
| Repeat preferences/discipline every session | Feedback persisted; Read auto-bumps last_access so LRU doesn't kill read-heavy rules |
| Can't find the right memory in a pile | JSONL index, O(1) jq lookup |
| Long projects → context bloat | 30d × 3 auto-compaction; critical decisions kept forever |
| Same-named branches across cwds collide | Strict cwd-slug isolation; monorepo subproject support |

---

## 🎯 Pain points it solves

If you use Claude Code heavily, these will be familiar:

1. **Context amnesia** — every new session re-explains everything
2. **Branch-switch blackout** — switch away from `feat/X`, come back, forgot what you were doing
3. **Discipline drift** — same rule repeated to Claude every session
4. **Memory black-hole** — 50+ markdown notes, can't find the right one
5. **Monorepo collisions** — same branch name across subprojects, memories cross-contaminate
6. **Context bloat** — useful facts buried in hundreds of unimportant ones

---

## 💡 How Memex solves them

**Core philosophy: static rules in scripts, dynamic judgment in LLM** (Listener + Handler).

```
              ┌─────────────────┐
              │  Claude Code    │
              │   (Handler)     │
              └────────┬────────┘
                       │ tools
                ┌──────▼──────┐
                │   Hooks     │ ← event listener
                │  (5 of them)│   inject facts, never decide
                └──────┬──────┘
                       │ ctx injection / index sync
        ┌──────────────▼──────────────┐
        │   ~/.claude/projects/<cwd>/  │
        │   memory/                    │
        │   ├── INDEX.md(human-read)   │
        │   ├── _index/*.jsonl         │
        │   ├── feedback/              │
        │   ├── reference/             │
        │   └── projects/<biz>/        │
        │       └── branches/<slug>.md │
        └──────────────────────────────┘
```

### 5 hooks (all event listeners)

| Hook | Trigger | What it does |
|---|---|---|
| `session-bootstrap.sh` | First tool call | Creates skeleton in new cwd / auto-reindex on drift |
| `pre-read-memory-bump.sh` | Read | Updates last_access so read-heavy rules survive LRU |
| `check-protected-branch.sh` | Bash | Blocks commit/push to protected branches; injects memory on checkout |
| `pre-edit-branch-notice.sh` | Edit/Write | Reminds branch memory before editing |
| `post-write-memory-sync.sh` | Write/Edit | Auto-indexes new memory files |

### 3 Python CLI tools

| Tool | What it does |
|---|---|
| `rebuild_index.py` | Full reindex (LRU fields preserved) |
| `update_index_md.py` | Regenerates INDEX.md marked blocks from jsonl |
| `lru_compact.py` | LRU scan + branch-deletion detect + `--mark`/`--pin`/`--unpin` |

### Key design decisions

- **JSONL, not SQLite** — LLM-readable, no injection risk, scales to thousands, easy to degrade
- **One mem_root per cwd** — strict isolation, no cross-cwd glob (prevents same-name branch collision)
- **status × decay matrix** — `pinned` never evicted / `active` auto-demotes after 30d / `dormant` walks the compaction ladder
- **30d × 3 compaction** — 90 days to deletion candidate, +30 days to actual delete = 120-day buffer
- **Fallback ctx loop** — script parse failure → ⚠️ ctx tells LLM to take over, **never silent fail**
- **Scripts don't parse complex shell** — only `cd <path>` / `git -C <path>` are recognized; everything else falls through to LLM

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

---

## 📂 Directory layout

```
Global (install once):
~/.claude/
├── MEMORY_SPEC.md              single source of truth (9 sections)
├── INDEX_TEMPLATE.md
├── hooks/
│   ├── session-bootstrap.sh
│   ├── pre-read-memory-bump.sh
│   ├── check-protected-branch.sh
│   ├── pre-edit-branch-notice.sh
│   └── post-write-memory-sync.sh
└── bin/
    ├── rebuild_index.py
    ├── update_index_md.py
    └── lru_compact.py

Per-cwd workspace (auto-created):
~/.claude/projects/<cwd-slug>/memory/
├── INDEX.md                    human-read entry + AUTO marker blocks
├── MEMORY.md → INDEX.md        symlink (Claude system prompt picks this up)
├── _index/
│   ├── meta.jsonl              one line per memory (LRU + decay + size)
│   └── by_branch.jsonl         (project, branch) → memory inverted index
├── feedback/                   discipline / rules (read-heavy)
├── reference/                  external system refs
├── user/                       user profile
├── global/                     project-level cross-business docs
└── projects/
    └── <business>/
        ├── overview.md
        ├── *.md
        └── branches/
            └── <branch_slug>.md
```

---

## 🚀 Install in 3 steps

### Dependencies

- `jq`
- `python3` ≥ 3.8
- `git`
- [Claude Code](https://docs.claude.com/en/docs/claude-code)

### Install

```bash
git clone https://github.com/<your-fork>/harness-memex.git
cd harness-memex
./install.sh
```

This will:
1. Check deps
2. Copy hooks to `~/.claude/hooks/`
3. Copy bin to `~/.claude/bin/`
4. Copy MEMORY_SPEC + INDEX_TEMPLATE to `~/.claude/`
5. Merge hook registrations into `~/.claude/settings.json` (auto-backup, no overwrite)
6. chmod +x

**Restart Claude Code** to activate hooks.

### Verify

In a new session, any cwd, run a bash:
```
ls ~/.claude/projects/$(pwd | sed 's#/#-#g')/memory/
```

If you see `INDEX.md _index/ feedback/ projects/ ...`, you're set.

---

## 🔧 Config (all optional)

In `~/.zshrc` / `~/.bashrc`:

```bash
# Custom protected branches (default: main master develop production)
export MEMEX_PROTECTED_BRANCHES="main master develop staging production release"

# Custom LRU period in days (default: 30)
export MEMEX_LRU_PERIOD_DAYS=30
```

---

## 📖 What it looks like in use

### A — first Claude session in a new cwd

```
cd ~/project/myapp
claude
Claude runs any bash → bootstrap hook fires
  → ~/.claude/projects/-Users-x-project-myapp/memory/ skeleton created
  → INDEX.md from template, _index/ empty
  → Claude receives ctx: "✨ workspace initialized, read INDEX.md first"
```

### B — you say "remember to use conventional commits"

```
Claude writes memory/feedback/conventional-commits.md
post-write-memory-sync hook → auto-indexes into meta.jsonl
Next session, INDEX.md already lists it under "Feedback / Discipline"
```

### C — branch switch

```
You: "switch to feat/<date>/login"
Claude runs: cd subdir && git checkout feat/<date>/login
check-protected-branch hook fires:
  → archive: current branch feat/<date>/profile memory path (LLM should remind you to fill in)
  → recall: target feat/<date>/login memory content (first 200 lines) injected into ctx
  → After checkout, LLM immediately knows the prior state
```

### D — old branch unused for 90 days

```
You run: python3 ~/.claude/bin/lru_compact.py
Tool lists: 5 entries 30d+ dormant ready for compaction round 1, 2 entries 60d+...
You: "compact these 5"
LLM Reads each → writes compact version → lru_compact.py --mark <path> 1
```

---

## ❓ What it doesn't do (by design)

- ❌ Doesn't parse complex shell (pushd / subshell / quoted paths / aliases) — **intentional**; LLM takes over on failure
- ❌ Doesn't run LRU scan automatically (manual `lru_compact.py`; future P2)
- ❌ Doesn't replace git — memory is your personal long-term notes, not versioned
- ❌ Doesn't reduce token cost — ctx injection adds tokens

---

## 🗑️ Uninstall

```bash
./uninstall.sh
```

- Removes `~/.claude/hooks/{5 files}.sh` and `~/.claude/bin/{3 tools}.py`
- Removes hook registrations from `~/.claude/settings.json` (backup kept)
- **Keeps all `~/.claude/projects/*/memory/`** — your workspace is safe

---

## 🤝 Contributing

- New hooks → add to `hooks/`, register in `install/memex-hooks.json`
- New tools → add to `bin/`, document in `docs/CLI.md`
- Docs → any `.md` under `docs/`
- Examples → add scenarios to `examples/`

See [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## 📚 Inspirations

- **Anthropic** — [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- **Anthropic** — [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- **Vannevar Bush** — [*As We May Think* (1945)](https://www.theatlantic.com/magazine/archive/1945/07/as-we-may-think/303881/)
- **Linux kernel** — *mechanism not policy* (hook = mechanism, LLM = policy)
- **Redis** — eviction policies (LRU state machine reference)
- **Nginx** — master-worker signal control (hook silent-degrade on failure)

---

## 📄 License

[MIT](./LICENSE)

---

If this helped, drop a ⭐. Found a bug? Open an issue. Have an idea? Open a PR.
