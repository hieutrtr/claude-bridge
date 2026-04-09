# W2.6: Cross-Compatibility Test Suite

## Description
Verify TS-created databases pass integrity checks and match Python schema.

## Acceptance Criteria
- [ ] TS-created bridge.db passes PRAGMA integrity_check
- [ ] TS-created messages.db passes PRAGMA integrity_check
- [ ] All expected tables exist in bridge.db
- [ ] All expected tables exist in messages.db
- [ ] Column names match Python schema
- [ ] Data roundtrip: create→read works for all entity types
