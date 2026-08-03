# VibeCode Control node assignment

Send this text to the session named `{{session}}`. This CLI does not send it: it prints the assignment, and delivery stays with the coordinator.

**Node:** `{{node}}` (role `{{role}}`)
**Issue:** {{issue}}
**Head SHA:** `{{head_sha}}`
**Authorization:** {{authorization_kind}} `{{authorization_ref}}`

Run the preflight first and stop unless it returns `PASS`:

```bash
{{preflight_command}}
```

Report `PARTIAL` or `BLOCKED` rather than inventing executor, model, effort, skill, GitHub, or CI availability. Load `devflow-node` explicitly, then every skill the preflight names as assigned to this node.

Expected evidence for this node:

{{expected_evidence}}

Bind every artifact to the head SHA above. A new commit invalidates this assignment: ask for a fresh one instead of reporting against a stale SHA.

Answer with the run record identifier produced by:

```bash
{{record_command}}
```

If this session dies mid-node, the node is restarted whole from the last recorded run record. Nobody continues a dead session from the middle: the run record and its head SHA are the checkpoint.
