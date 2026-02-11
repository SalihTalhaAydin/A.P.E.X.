# Cursor IDE: Rules, Skills, Commands, Subagents — Research Summary

Deep research on the **right way** to use Cursor’s rules, skills, commands, and subagents, and how your setup compares to what exists on GitHub and in the docs.

---

## 1. Is writing to `state.vscdb` the right way?

**Short answer: No. It’s a workaround, not the intended mechanism.**

- **Where User Rules actually live**: Cursor stores “Rules for AI” (User Rules) in the app. On disk they end up in the SQLite DB `state.vscdb` under the key `aicontext.personalContext` (Windows: `%APPDATA%\Cursor\User\globalStorage\state.vscdb`).
- **Official stance**: User Rules are “defined in Cursor Settings → Rules” and are “plain text only.” There is **no documented** “global rules from file” or “sync from ~/.cursor/” flow. The forum and a Cursor staff reply say a **global rules directory** (e.g. `~/.cursor/rules`) **does not exist** and is a requested feature.
- **Cloud sync**: In newer versions, rules can be stored in the cloud; the local DB may not reflect what you set in the UI, or your local write can be overwritten when Cursor syncs.
- **Recommendation**: Treat writing to `state.vscdb` as an **optional sync script** (e.g. “copy from `cursor-user-rules-recommended.md` into the DB when I want”), not as the single source of truth. The **supported** approach is: keep your canonical text in a file (e.g. `~/.cursor/cursor-user-rules-recommended.md`) and **paste it into Cursor Settings → Rules (User Rules)** when you change it. If you script the DB write, do it knowing it can be overwritten by sync.

---

## 2. How rules, commands, skills, and subagents are meant to be used

From Cursor docs and the forum (e.g. “Skills vs. Commands [vs. Rules]”):

| Mechanism   | Where it lives | When it’s used | Best for |
|------------|-----------------|----------------|----------|
| **Rules**  | Project: `.cursor/rules/*.mdc`. User: Settings → Rules (plain text). | Rules: always / glob / agent‑decided / manual (@rule). User Rules: every chat. | Short, stable instructions: style, architecture, “never do X.” Keep under ~500 lines. |
| **Commands** | Project: `.cursor/commands/*.md`. User: `~/.cursor/commands/*.md`. | You (or the agent) trigger via `/` in chat. | Repeatable workflows: “code review,” “run tests and fix,” “security audit,” “create PR.” |
| **Skills** | Project: `.cursor/skills/<name>/SKILL.md`. User: `~/.cursor/skills/<name>/SKILL.md`. | Agent **decides** when relevant, or you invoke via `/`. Open standard (agentskills.io). | Domain knowledge and procedures; can include `scripts/`, `references/`, `assets/`. Loaded when relevant. |
| **Subagents** | `.cursor/agents/*.md` or `~/.cursor/agents/*.md`. | You delegate or agent uses for isolated/parallel work. | Complex, multi-step or parallel tasks with separate context. |

- **Rules**: Prefer **project** rules in `.cursor/rules/` as `.mdc` (with `description`, `globs`, `alwaysApply`). Use **User Rules** in Settings for personal, global preferences (concise; no .mdc).
- **Commands**: Only run when invoked (e.g. via `/`). Good for “do this workflow once.”
- **Skills**: Can be applied **automatically** when the agent thinks they’re relevant, or manually via `/`. Good for “whenever we’re doing X, use this knowledge.”
- **Subagents**: Isolated context; can run in parallel. Use for big, separable tasks.

So: **rules** = always/minimal context; **commands** = on-demand workflows; **skills** = richer, agent-chosen or manual; **subagents** = parallel/isolated work.

---

## 3. What’s on GitHub and in the community

### Rules

- **digitalchild/cursor-best-practices**: Rule types, precedence (Local → Auto-attached → Agent-requested → Always), User vs Project rules, .mdc structure. User Rules = plain text in Settings only.
- **sparesparrow/cursor-rules**: Hierarchical `.cursor/rules/` (core, framework, domain, security, patterns) with .mdc and metadata (description, globs, priority, dependencies). Good template for “enough” rules.
- **get-rules** (npm: `npx get-rules`): Fetches .mdc rules from a repo into `.cursor/rules/` (e.g. `_always/`, `_globs/`, cli, docs, git, task). Use to bootstrap a full rule set; keep personal rules in `_/` (gitignored).
- **cursor.directory**: Large index of rules by language/framework (TypeScript, Python, React, etc.). “Global” page shows example User Rules (paste into Settings).
- **Cursor docs**: Prefer .mdc in `.cursor/rules/`; legacy `.cursorrules` deprecated. Rules under 500 lines; one concern per rule; use globs and description so the agent can choose.

### Commands

- **hamzafer/cursor-commands** (featured by Cursor): 30+ slash commands in `.cursor/commands/`, e.g. `code-review.md`, `run-all-tests-and-fix.md`, `lint-fix.md`, `security-audit.md`, `generate-pr-description.md`, `refactor-code.md`, `write-unit-tests.md`, `debug-issue.md`, etc. Structure: objective, requirements, output. Project commands in repo; global in `~/.cursor/commands/`. This is the de facto “standard” for “enough” commands.
- **Cursor docs**: Commands are .md files; type `/` to list and run. Stored in `.cursor/commands/` (project) or `~/.cursor/commands/` (global). Some users report global commands not detected in some builds—worth verifying on your install.

### Skills

- **agentskills.io**: Open standard. Each skill = folder with `SKILL.md` (required). Optional: `scripts/`, `references/`, `assets/`. Frontmatter: `name`, `description` (required); optional `license`, `compatibility`, `metadata`, `disable-model-invocation`. Name = folder name; description used for relevance.
- **Cursor 2.4**: Skills loaded from `.cursor/skills/` and `~/.cursor/skills/` (and .claude/.codex for compatibility). Agent can apply skills when relevant, or you invoke via `/`. Built-in `/migrate-to-skills` converts “Apply Intelligently” rules and slash commands to skills (commands become skills with `disable-model-invocation: true`).

### Subagents

- **create-subagent skill**: Project agents in `.cursor/agents/`, user agents in `~/.cursor/agents/`. Each is a .md file with frontmatter (`name`, `description`) and a system prompt. Used for focused, isolated, or parallel tasks.

---

## 4. Gaps in your current setup (and how to fix them)

- **User Rules**: You have a single markdown file and a DB write. That’s fine as a **personal** source of truth, but the “right” supported way is: file as canonical text → paste into **Cursor Settings → User Rules**. DB write = optional automation with sync caveats.
- **“Not enough” rules**: You have a few project rules (apex-project, change-tracking, apex-orchestration) and one user-level blob. Compared to:
  - get-rules (_always, _globs, cli, docs, git, task),
  - sparesparrow (core/framework/domain/security/patterns),
  - cursor.directory (many per stack),
  you have relatively few. Adding more **project** rules (e.g. Python/FastAPI, testing, git) from cursor.directory or get-rules would align with “best” practice.
- **“Not enough” commands**: You have a couple of user-level commands (implement, add-preference-rule). hamzafer/cursor-commands has 30+ (review, test, lint, security, docs, git, etc.). Cloning or copying that set into `~/.cursor/commands/` (and optionally into APEX’s `.cursor/commands/`) would match how others get “enough” commands.
- **Skills**: Your “implementer” and “rule-capturer” are in **subagents** (`~/.cursor/agents/`). The **recommended** pattern for “agent decides when to use this” is **Skills** in `~/.cursor/skills/<name>/SKILL.md` (agentskills.io format). So:
  - Move (or duplicate) implementer and rule-capturer into `~/.cursor/skills/implementer/SKILL.md` and `~/.cursor/skills/rule-capturer/SKILL.md` with proper frontmatter and body. Then the agent can auto-apply them when relevant, and you can still invoke via `/`.
  - Keep subagents for true “separate agent” / parallel workflows if you use them.
- **Structure**: Community best practice is a clear hierarchy (e.g. _always, _globs, by-domain) and use of get-rules or similar to bootstrap and sync. You don’t need to over-engineer, but adding a bit of structure (e.g. _always for “always apply” project rules) would align with digitalchild/sparesparrow/get-rules.

---

## 5. Recommended “right” way (summary)

1. **User Rules**
   - Keep canonical text in `~/.cursor/cursor-user-rules-recommended.md`.
   - **Primary**: Paste (or re-paste) that content into **Cursor Settings → Rules (User Rules)** when you update it.
   - **Optional**: Use a script that writes the file contents into `state.vscdb` (key `aicontext.personalContext`) for convenience, knowing cloud sync may overwrite it.

2. **Project rules**
   - Keep using `.cursor/rules/*.mdc` with description/globs/alwaysApply.
   - Add more rules from cursor.directory or get-rules for your stack (e.g. Python, FastAPI, testing).
   - Optionally run `npx get-rules` once to get a full structure, then keep only what you need and add APEX-specific rules.

3. **Commands**
   - Add many more: copy or clone **hamzafer/cursor-commands** into `~/.cursor/commands/` (global) and/or into APEX’s `.cursor/commands/` (project).
   - Keep your custom “implement” and “add-preference-rule” as additional commands.

4. **Skills**
   - Put “implementer” and “rule-capturer” (and any other “use when relevant” behaviors) in **Skills** under `~/.cursor/skills/<name>/SKILL.md` per agentskills.io (name, description, body; optional scripts/references).
   - Use Cursor’s **Settings → Rules** to confirm skills appear under “Agent Decides.” Optionally use `/migrate-to-skills` to convert existing dynamic rules/commands to skills.

5. **Subagents**
   - Keep `~/.cursor/agents/` for tasks that really need a **separate** agent or parallel run (e.g. “code reviewer” subagent). Use for isolated context, not for “same agent, different instructions” (that’s skills).

6. **Don’t rely only on state.vscdb**
   - Treat DB writing as a convenience, not the official path. The supported path is Settings → User Rules and, for project scope, files in `.cursor/rules/`.

---

## 6. Links

- [Cursor Docs: Rules](https://cursor.com/docs/context/rules)
- [Cursor Docs: Commands](https://cursor.com/docs/context/commands)
- [Cursor Docs: Skills](https://cursor.com/docs/context/skills)
- [Cursor Docs: Subagents](https://cursor.com/docs/context/subagents)
- [Agent Skills spec](https://agentskills.io/specification)
- [hamzafer/cursor-commands](https://github.com/hamzafer/cursor-commands) — commands
- [digitalchild/cursor-best-practices](https://github.com/digitalchild/cursor-best-practices) — rules best practices
- [sparesparrow/cursor-rules](https://github.com/sparesparrow/cursor-rules) — rule hierarchy
- [get-rules (npm)](https://github.com/johnlindquist/get-rules) — bootstrap .cursor/rules
- [cursor.directory](https://cursor.directory/) — rule index and examples
- [Forum: Skills vs Commands vs Rules](https://forum.cursor.com/t/skills-vs-commands-vs-rules/148875)
- [Forum: Where global rules saved](https://forum.cursor.com/t/where-are-the-global-rules-saved-in-my-filesystem/76645)
