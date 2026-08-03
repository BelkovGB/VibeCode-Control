# Test specification

Written on the `design` node, consumed by `tdd_red`. The node that writes the tests does not invent conditions: an ambiguous or incomplete specification is `BLOCKED` and goes back, it is never improvised into something plausible.

Check the structure before the tests are written:

```bash
devflow spec check <path>
```

## Criteria

Every criterion this change is accountable for, with a stable identifier. Use `FR-###` for a functional requirement, `SC-###` for a success criterion, `US#` for a user story and `AC#` for an acceptance criterion. A success criterion is measurable and technology-agnostic: it states what becomes true for the user, not which library does it.

- `FR-001` — <what the system must do>
- `SC-001` — <what becomes measurably true>

## Cases

One case per block. Every case names the criterion it covers, its test type, the Given/When/Then triple, and the reason the test is expected to fail before the change exists. The expected failure reason is what makes a red test evidence instead of a formality: a test that fails for the wrong reason proves nothing.

### CASE-001

- Criterion: `FR-001`
- Type: `unit`
- Given: <the state the system starts in>
- When: <the action under test>
- Then: <the observable outcome>
- Expected failure reason: <why this fails today — missing function, wrong branch, absent validation>

### CASE-002

- Criterion: `SC-001`
- Type: `integration`
- Given: <...>
- When: <...>
- Then: <...>
- Expected failure reason: <...>

## What the checker does and does not verify

`devflow spec check` verifies the structure and the two-way link inside this document: every case carries its triple, its type from `unit | integration | contract | e2e`, its expected failure reason and a criterion declared above, and every declared criterion is covered by at least one case. Identifiers are unique.

It does not verify that these identifiers match the acceptance criteria of the actual Issue, and it never claims to. That correspondence is the reviewer's, and it is the reason the Issue reference belongs in the run record.
