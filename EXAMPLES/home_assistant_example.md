# Home Assistant Stewardship Mapping

This example shows how to wire the stewardship loop into Home Assistant without embedding the agent in HA itself.

## Flow
1. Agent proposes a script call with parameters and rollback.
2. Stewardship Gate renders an explanation and requests approval.
3. Human clicks a confirmation `input_button` or denies via a dashboard card.
4. On approval, the gate triggers a Home Assistant `script` or `scene` call.
5. Audit log records proposal, decision, and execution result.

## Entities
- `input_text.proposal_summary`: human-readable summary from the gate.
- `input_button.approve` / `input_button.deny`: user controls wired to the gate via webhook or MQTT.
- `script.stewardship_execute`: executes only after approval; accepts target entity and parameters.
- `sensor.stewardship_status`: exposes latest decision/result for observability.

## Safety notes
- Only register scripts corresponding to allowlisted actions/resources.
- Deny by default if no decision arrives within a timeout.
- Record every step to an append-only audit log (e.g., JSONL pushed to a file or HTTP endpoint).
- Prefer reversible actions: scenes and toggles before irreversible service calls.
