---
name: writing-skills
description: How to author a new skill or improve an existing one for this project.
when_to_use: When you need to create a new skill file, or revise one that was unclear, wrong, or incomplete.
tier: any
---

# Writing and improving skills

A **skill** is a self-contained runbook that teaches the agent one competency,
so that any model — especially a weak one — can perform the task reliably by
following it literally. A skill is an operating procedure, not an essay.

## 1. Anatomy

One markdown file in `skills/`, YAML front matter:

```yaml
---
name: kebab-case-name          # unique; matches the filename without .md
description: One line, what it does.
when_to_use: The trigger — the situation in which the agent should load this.
tier: any | weak-ok | strong-recommended
---
```

Body, in this order:
1. **Goal** — one sentence: what "done" looks like.
2. **When to use / when NOT to use.**
3. **Preconditions** — inputs, tools, environment (exact venv path, packages).
4. **Procedure** — numbered, literal steps with exact commands/code.
5. **Runnable snippet** — copy-pasteable, using `.venv/bin/python`.
6. **Interpretation & pitfalls** — how to read output; known failure modes;
   which HARD RULES from `CLAUDE.md` apply.
7. **Cross-links** — related skills.

## 2. Principles

- **Literal beats clever.** Exact commands, not descriptions of commands.
- **One competency per skill.** Two unrelated procedures → split.
- **Deterministic core.** Numbers come from code, not prose; include the code.
- **Cite sources.** Every external fact (API field, format spec) carries its
  URL and the date it was verified (CLAUDE.md research rule).
- **Feed pitfalls back.** When a session hits a reusable trap, append it to
  the matching skill's pitfalls section in the same task loop (step 6),
  and update `skills/README.md` status if a 🟡 skill got written.
