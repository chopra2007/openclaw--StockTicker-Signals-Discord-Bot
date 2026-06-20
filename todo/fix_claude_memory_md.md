# Fix Claude MEMORY.md

**Status:** DONE 2026-06-20
**Created:** 2026-06-20

## Outcome (2026-06-20)

Done via modified Option A — compacted the index only, kept the one-fact-per-file structure (no 13-file consolidation, no merges/duplication). MEMORY.md: 134 lines/27,976 bytes → 140 lines/15,030 bytes (~14.7KB, under the 25KB load limit). Fixed one pre-existing broken link (`signal-features Phase 1` pointed at `#`) by creating `project_signal_features_phase1.md`. All 125 links resolve; zero topic files deleted. CLAUDE.md left untouched (rules already present). Backups: `MEMORY.md.pre-refactor-bak` + `MEMORY.md.backup-2026-06-20`.

## Goal

Restructure MEMORY.md according to claude_memory_refactor_prompt.md

## Background

- File path: `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md`
- Backup: `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md.backup-2026-06-20`
- Current size: 28KB, 134 lines (over OMC's 24.4KB limit — only part of it loads per session)

## Execution prompt

User-designed prompt for carrying out this refactor (the actual instructions for fixing MEMORY.md):
`/home/openclaw/.openclaw/workspace/todo/claude_memory_refactor_prompt.md`

## Reference

Use the backup as the source of truth if anything is lost during editing:
`/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md.backup-2026-06-20`
