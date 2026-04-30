# W2.2: BridgeDatabase Core (Agents + Tasks)

## Description
Implement BridgeDatabase with full schema DDL, WAL mode, agent CRUD, task CRUD,
atomic dispatch, and queue operations. This is the critical path foundation.

## Python Source
- `src/claude_bridge/db.py` — agent methods (7), task methods (9), queue methods (4), atomic_check_and_create_task

## Acceptance Criteria
- [ ] Full schema DDL matching Python (agents, tasks, permissions, teams, team_members, notifications, loops, loop_iterations, schedules + indexes)
- [ ] WAL mode + foreign keys ON
- [ ] Agent CRUD: create, get, getBySession, list, delete, updateState, incrementTasks, updateModel
- [ ] Task CRUD: create, get, getRunningTask, getRunningTasks, getUnreportedTasks, getTaskHistory, updateTask, markTaskReported
- [ ] Atomic dispatch: atomicCheckAndCreateTask with BEGIN EXCLUSIVE
- [ ] Queue ops: getQueuedTasks, getNextQueuePosition, dequeueNextTask, cancelQueuedTask
- [ ] Column whitelist enforcement on updateTask
