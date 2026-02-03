# Samuel-style Gate Example

Samuel combines a Home Assistant stack, a reasoning "Brain," and a Stewardship Gate. The Brain produces proposals, but the Gate mediates every change.

## Architecture
- Brain (LLM/logic) emits proposals with desired Home Assistant actions.
- Stewardship Gate normalizes, explains, applies allowlists/safe domains, and asks a human steward.
- Home Assistant executes only after APPROVE or auto-approve inside safe domains.
- Audit log captures proposal_id and trace_id across steps.

## Example transcript
```
Agent: Propose turning on porch_light for 15 minutes; rollback is turn off.
Gate: Summary: toggle porch_light for 15 minutes. Safe domain: lighting? Yes. Risks: minimal. Approve?
Human: APPROVE (reason: routine)
Gate: Executing... success. Logged proposal_id=pl-042, trace_id=t-883.
Gate: Learn: duration=15m; feedback=ok.
```

## Sample allowlist
- Actions: `turn_on`, `turn_off`, `set_brightness`, `set_scene`.
- Resources: entities tagged `safe_light`, `safe_switch`.
- Max duration: 30 minutes.

## Safe domains
- Lighting scenes in shared spaces.
- Test/sandbox Home Assistant instances.
- Read-only diagnostics.
