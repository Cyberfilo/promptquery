## What & why

<!-- What does this change and why? Link any issue: Closes #123 -->

## Checklist
- [ ] `pytest` passes locally
- [ ] `ruff check .` is clean
- [ ] Did not weaken `tests/test_safety.py` (safety cases are load-bearing)
- [ ] Both read-only layers (`db.py` session + `safety.py` guard) intact
- [ ] README/CHANGELOG updated if behaviour changed
- [ ] If the eval changed, committed the receipts (incl. failures)

## How tested
<!-- commands / output -->
