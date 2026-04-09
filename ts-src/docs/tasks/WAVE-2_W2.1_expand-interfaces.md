# W2.1: Expand IDatabase Interface

## Description
Expand IDatabase from 20 to ~55 methods. Add IMessageDatabase. Update types.ts with full schemas.

## Acceptance Criteria
- [ ] IDatabase has all methods matching Python db.py (agents, tasks, queue, loops, schedules, permissions, notifications, teams, cost)
- [ ] IMessageDatabase interface for message_db.py operations
- [ ] ISessionManager expanded to ~10 methods
- [ ] types.ts expanded with all entity types (Agent, Task, Loop, Schedule, Permission, Notification, Team, InboundMessage, OutboundMessage)
- [ ] All types match Python SQLite schema column names and types
