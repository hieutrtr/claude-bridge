# W2.3: BridgeDatabase Extended (Loops, Schedules, Permissions, Notifications, Teams)

## Description
Test and verify extended database operations: loop CRUD + iterations,
schedule CRUD + due query, permission relay, notification queue, team ops, cost summary.

## Acceptance Criteria
- [ ] Loop CRUD: create, get, getActiveForAgent, update, listLoops, getByTaskId
- [ ] Loop iterations: create, update, getIterations, getLastN
- [ ] Schedule CRUD: add, getByName, getById, getDue, updateSuccess, updateError, list, remove, pause, resume
- [ ] Permission: create, get, getPending, respond, timeout
- [ ] Notification: create, get, getPending, markSent, markFailed
- [ ] Team: create, get, getMembers, list, delete
- [ ] Cost summary with period filtering
