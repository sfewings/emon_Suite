# Claude Working Instructions — emon_Suite

## Git Workflow
- Always prepare a commit message and ask before committing — never commit without explicit user approval
- Never push to remote without explicit instruction
- Stage only files relevant to the current change; do not mass-stage unrelated files
- Use conventional commit style: `scope: short summary` followed by a body explaining *why*

## Project Context
The primary active project is the **emon event_recorder**.

Living requirements document (read at the start of any event_recorder session):
`python/event_recorder/docs/EVENT_RECORDER_REQUIREMENTS.md`

This document is the authoritative source for:
- Feature requirements and completion status
- Architectural decisions and design rationale
- Database schema and API contracts
- Known bugs and their fixes

## Code Style
- Python: follow existing patterns in the file being edited; no unnecessary refactoring
- Do not add docstrings, comments, or type annotations to code that was not changed
- Keep changes minimal and focused — do not "improve" surrounding code unless asked

## Testing Environment
- Docker Compose stack in `python/event_recorder/test_event_recorder/`
- Test data lives in `python/event_recorder/test_event_recorder/data/` (git-ignored)
- WordPress instance runs locally via Docker for integration testing
