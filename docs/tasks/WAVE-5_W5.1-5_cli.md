# Wave 5: CLI & Integration (W5.1-W5.5)

## W5.1: CLI framework + core commands
- Arg parsing with command router
- 5 core commands: create-agent, delete-agent, list-agents, status, dispatch
- Output formatting matching Python CLI

## W5.2: CLI extended commands
- kill, history, loop, schedule subcommands, cost, set-model, memory
- Loop: loop, loop-status, loop-cancel, loop-approve, loop-reject, loop-list, loop-history
- Schedule: schedule-add, schedule-remove, schedule-list, schedule-pause, schedule-resume

## W5.3: AgentMdGenerator
- YAML frontmatter generation (tools, isolation, memory, hooks)
- Markdown body with purpose and behavior rules
- Stop hook injection in project settings

## W5.4: ClaudeMdInit + Memory reader
- Auto-init CLAUDE.md via claude -p subprocess
- Memory reader: find memory dir, read MEMORY.md + topics

## W5.5: CLI snapshot tests
- Output format tests for core commands
- Verify create/delete/list/dispatch/status
