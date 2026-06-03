# Memex

> **Branch-aware extension pack for Claude Code Auto Memory**
> Named after Vannevar Bush's 1945 *Memex* concept.

> **Does not replace** Anthropic Auto Memory (built-in since v2.1.59+, covers ~80%).
> **Adds 4 things Auto Memory does not do**: ① per-project × per-branch memory (git origin-keyed) ② 3-way JSONL index (projects/branches/meta) ③ explicit LRU + soft-delete ④ worktree-safe (bypasses [issue #39920](https://github.com/anthropics/claude-code/issues/39920)).
>
> **v0.2** — full project-key isolation; see [CHANGELOG](./CHANGELOG.md).

Turn one-shot Claude Code sessions into a **cross-session, cross-branch, cross-cwd long-term workspace** that accumulates over time.

[中文 README](./README.md) · [Architecture](./docs/ARCHITECTURE.md) · [Motivation](./docs/MOTIVATION.md) · [Quick install](#-install-in-3-steps)

---

## ⚡ 30-second pitch

| Before (vanilla Claude Code) | After (with Memex) |
|---|---|
| Re-explain project context every new session | LLM auto-loads `MEMORY.md` bridge → `@import` global + per-project INDEX |
| Forget where you left off when switching branches | Branch checkout auto-saves from + auto-loads to (memory injected into ctx) |
| Repeat preferences/discipline every session | Feedback persisted; Read auto-bumps last_access so LRU doesn't kill read-heavy rules |
| Can't find the right memory in a pile | 3-way JSONL index (`projects`/`branches`/`meta`), O(1) jq lookup |
| Long projects → context bloat | 30d × 3 auto-compaction; critical decisions kept forever |
| Same-named branches across projects collide | Project-key (git origin) isolation; worktree / monorepo / multi-cwd all consistent |

---

## 🎯 Pain points it solves

If you use Claude Code heavily, these will be familiar:

1. **Context amnesia** — every new session re-explains everything
2. **Branch-switch blackout** — switch away from `feat/X`, come back, forgot what you were doing
3. **Discipline drift** — same rule repeated to Claude every session
4. **Memory black-hole** — 50+ markdown notes, can't find the right one
5. **Monorepo / multi-cwd collisions** — same branch name across subprojects, memories cross-contaminate
6. **Context bloat** — useful facts buried in hundreds of unimportant ones
7. **Worktree confusion** — Claude Code's `git-common-dir` resolution ([issue #39920](https://github.com/anthropics/claude-code/issues/39920)) maps all worktrees to the main one, so per-worktree state gets mixed

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
                │  (7 of them)│   inject facts, never decide
                └──────┬──────┘
                       │ ctx injection / index sync
        ┌──────────────▼──────────────────────┐
        │  Claude Code native (untouched)     │
        │  ~/.claude/projects/<cc-slug>/memory/│
        │  └── MEMORY.md ← memex bridge       │
        │       └── @import lines below ─────┼─┐
        └──────────────────────────────────────┘ │
        ┌──────────────────────────────────────┐ │
        │  Memex global pool (project-keyed,  │◄┘
        │  no cwd dimension)                   │
        │  ~/.claude/memex/                    │
        │  ├── _index/{projects,branches,meta} │
        │  ├── global/{feedback,reference,...} │
        │  └── projects/<project-key>/         │
        │      └── branches/<slug>.md          │
        └──────────────────────────────────────┘
```

### 7 hooks (all event listeners)

| Hook | Trigger | What it does |
|---|---|---|
| `session-bootstrap.sh` | PreToolUse * | Scans cwd subdirs for all git repos, ensures memex skeleton, appends `<!-- memex:bridge -->` to Claude's `MEMORY.md` |
| `pre-read-memory-bump.sh` | Read | Updates last_access so read-heavy rules survive LRU |
| `check-protected-branch.sh` | Bash | Blocks commit/push to protected branches |
| `pre-edit-branch-notice.sh` | Edit/Write | derive_project_key + lookup branches.jsonl, reminds branch memory |
| `post-checkout-handoff.sh` | PostToolUse Bash | After git checkout/switch, tells LLM to parallel Write from-memory + Read to-memory |
| `post-write-memory-sync.sh` | Write/Edit | Auto-rebuild 3 jsonl + refresh INDEX.md on memex file change |
| `session-start-lru.sh` | SessionStart | Runs LRU scan at startup; if candidates, ctx-prompts LLM to compact |

### 6 Python CLI tools

| Tool | What it does |
|---|---|
| `derive_project_key.py` | git remote normalization + sha1[:12] → project_key (single source of identity) |
| `update_memex_bridge.py` | Scans cwd for git repos, idempotently replaces bridge block in Claude `MEMORY.md` |
| `rebuild_index.py` | Full reindex of 3 jsonl (LRU fields preserved) |
| `update_index_md.py` | Regenerates global + per-project INDEX.md AUTO blocks from jsonl |
| `lru_compact.py` | LRU scan + branch-deletion detect + `--mark`/`--pin`/`--unpin`/`--rm` |
| `migrate_v01_to_v02.py` | One-shot v0.1 → v0.2 migration (YAML mapping-driven) |

### Key design decisions (v0.2)

- **JSONL, not SQLite** — LLM-readable, no injection risk, scales to thousands, easy to degrade
- **project-key not cwd-slug** — derived from `git remote get-url origin` normalization + sha1[:12]; consistent across cwd / worktree / launch location
- **status × decay matrix** — `pinned` never evicted / `active` auto-demotes after 30d / `dormant` walks the compaction ladder
- **30d × 3 compaction** — 90 days to deletion candidate, +30 days to actual delete = 120-day buffer
- **Fallback ctx loop** — script parse failure → ⚠️ ctx tells LLM to take over, **never silent fail**
- **Scripts don't parse complex shell** — only `cd <path>` / `git -C <path>` are recognized; everything else falls through to LLM
- **Doesn't steal Auto Memory's write权** — bootstrap appends `<!-- memex:bridge -->` block to MEMORY.md tail, Claude's own writes are untouched
- **Bypasses [issue #39920](https://github.com/anthropics/claude-code/issues/39920)** — Claude Code uses `git-common-dir` which breaks worktrees; memex uses git origin directly

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

---

## 📂 Directory layout (v0.2)

```
Global (install once):
~/.claude/
├── MEMORY_SPEC.md                  single source of truth (v0.2, 11 sections)
├── MEMEX_GLOBAL_INDEX_TEMPLATE.md
├── MEMEX_PROJECT_INDEX_TEMPLATE.md
├── hooks/                          7 hooks
│   ├── session-bootstrap.sh        thin shell → update_memex_bridge.py
│   ├── pre-read-memory-bump.sh
│   ├── check-protected-branch.sh
│   ├── pre-edit-branch-notice.sh
│   ├── post-checkout-handoff.sh
│   ├── post-write-memory-sync.sh
│   └── session-start-lru.sh
└── bin/                            6 Python tools
    ├── derive_project_key.py
    ├── update_memex_bridge.py
    ├── rebuild_index.py
    ├── update_index_md.py
    ├── lru_compact.py
    └── migrate_v01_to_v02.py

Memex global pool (project-keyed, no cwd dimension):
~/.claude/memex/
├── _index/
│   ├── projects.jsonl              project-key → metadata
│   ├── branches.jsonl              (project_key, branch_slug) → memory_path inverted (O(1))
│   └── meta.jsonl                  one line per .md (LRU + decay + size)
├── global/
│   ├── INDEX.md                    every cwd @imports this
│   ├── feedback/                   cross-project discipline
│   ├── reference/                  cross-project external refs
│   └── *.md                        cross-project misc docs
└── projects/
    └── <project-key>/              one git repo = one key
        ├── INDEX.md                project facade (imported into Claude MEMORY.md)
        ├── overview.md
        ├── feedback/               project-specific
        ├── reference/              project-specific
        ├── *.md                    long-term decisions
        └── branches/
            └── <branch_slug>.md    only ONE place per branch

Claude Code native (untouched):
~/.claude/projects/<cc-slug>/memory/
└── MEMORY.md                       ← bootstrap idempotently appends memex:bridge block
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
2. Copy hooks to `~/.claude/hooks/` (7 hooks)
3. Copy bin to `~/.claude/bin/` (6 Python tools)
4. Copy `MEMORY_SPEC.md` + `MEMEX_GLOBAL_INDEX_TEMPLATE.md` + `MEMEX_PROJECT_INDEX_TEMPLATE.md` to `~/.claude/`
5. Merge hook registrations into `~/.claude/settings.json` (auto-backup, no overwrite)
6. chmod +x

**Restart Claude Code** to activate hooks.

### Verify

In a new session, any cwd, run a bash to trigger bootstrap, then:
```
ls ~/.claude/memex/                        # global pool root
cat ~/.claude/memex/_index/projects.jsonl  # projects detected under your cwd
```

If you see `_index/  global/  projects/` and projects.jsonl lists git repos under your cwd, you're set.

---

## 🔧 Config (all optional)

In `~/.zshrc` / `~/.bashrc`:

```bash
# Custom protected branches (default: main develop production staging)
export MEMEX_PROTECTED_BRANCHES="main master develop staging production release"  # 例子,可加自己仓库的

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
  → ~/.claude/memex/ skeleton ensured
  → Scans cwd subdirs for git repos, derive_project_key each
  → ~/.claude/memex/projects/<key>/ skeleton for each
  → Appends bridge block to ~/.claude/projects/<cc-slug>/memory/MEMORY.md
  → Claude receives ctx: "✨ Memex v0.2 initialized, N git repos detected, bridge installed"
```

### B — you say "remember to use conventional commits"

```
Claude decides if it's global or project-specific, writes:
  ~/.claude/memex/global/feedback/conventional-commits.md          (global)
  OR
  ~/.claude/memex/projects/<key>/feedback/conventional-commits.md  (project-specific)
post-write-memory-sync hook → auto-rebuild 3 jsonl + refresh INDEX.md
Next session, the bridge already @imports the corresponding INDEX
```

### C — branch switch

```
You: "switch to feat/<date>/login"
Claude runs: cd subdir && git checkout feat/<date>/login
post-checkout-handoff hook fires (PostToolUse Bash, after checkout completes):
  → derive_project_key for the repo
  → Look up branches.jsonl for both from and to branches (O(1) jq filter)
  → Inject ctx asking LLM to parallel-dispatch in same turn:
      · Write <from-memory-path>: save current state for from branch
      · Read <to-memory-path>: load target branch's progress/decisions/notes
  → After the parallel calls, Claude has full context for the new branch
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

- Removes `~/.claude/hooks/{7 files}.sh` and `~/.claude/bin/{6 tools}.py`
- Removes hook registrations from `~/.claude/settings.json` (backup kept)
- **Keeps `~/.claude/memex/` and `~/.claude/projects/*/memory/`** — your workspace is safe

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

## ❓ FAQ

### Q: Does it conflict with Claude Code's built-in CLAUDE.md?
**A**: No conflict — they're **complementary**. CLAUDE.md holds static project metadata; Memex manages the dynamic work surface. The bootstrap script idempotently appends a `<!-- memex:bridge -->` block to Claude's `MEMORY.md` — content: `@import` lines to the global INDEX + each active project's INDEX. **Doesn't steal Auto Memory's write权**. See [docs/AUTO-MEMORY-INTEGRATION.md](./docs/AUTO-MEMORY-INTEGRATION.md).

### Q: Will it slow down Claude Code?
**A**: Negligible overhead. Hooks average < 50ms per call; post-write-sync full reindex takes ~30ms at N=50 entries; LRU sweeps run manually, not in the hot path.

### Q: Will it increase Claude's token cost?
**A**: **Slightly reduces it on average.** You stop re-explaining your project every new session (the 5–10 min priming prompt goes away), and branch switches auto-inject memory instead of having the LLM Read multiple files to catch up. Hook ctx injection adds ~200–500 tokens per call — the savings on "re-explaining" far outweigh injection cost.

### Q: Does uninstalling lose my memory data?
**A**: No. `uninstall.sh` only removes hooks, tools, and settings.json registration. **All memory data stays in `~/.claude/projects/*/memory/`.** Reinstall with `install.sh` and pick up where you left off.

### Q: How does it compare to vector / RAG retrieval?
**A**: **Different design goals.** Vector RAG does semantic search over large unstructured corpora to answer user questions. Memex is structured work-surface memory, auto-maintained and auto-injected into context. They coexist nicely: Memex owns "my working state", RAG owns "the project doc library".

### Q: How does team collaboration work? Can memory be shared?
**A**: **Memory is personal by default** (under `~/.claude/`). For team sharing: symlink `feedback/` and `reference/` to a shared git repo and collaborate via PR. **Branch memory should not be shared** — it reflects personal development context and sharing pollutes it.

### Q: What if a hook loops or blocks me incorrectly?
**A**: Temporary disable: `mv ~/.claude/hooks ~/.claude/hooks.disabled`, then `mv` back after triage. `install.sh` always backs up settings before editing (`*.memex-backup-<timestamp>`); `cp` it back to recover.

### Q: Does it require Claude Code? Can Cursor / Aider use it?
**A**: **Claude Code only for now** (built on its hook API). It could be ported to Cursor / Aider / Cline (all have hook or plugin systems) — contributions welcome. Windows is untested; WSL / Git Bash recommended.

> More questions (20+ entries covering design philosophy, troubleshooting, roadmap): see [docs/FAQ.md](./docs/FAQ.md) (Chinese — English readers should still find it clear).

---

## 📄 License

[MIT](./LICENSE)

---

If this helped, drop a ⭐. Found a bug? Open an issue. Have an idea? Open a PR.
