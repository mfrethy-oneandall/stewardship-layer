# Schemas

JSON Schema definitions for the stewardship layer interfaces.

## Files

- **proposal.schema.json**: Structure of a proposal submitted to the gate
- **decision.schema.json**: Structure of a decision (approve/deny) on a proposal

## Validation

Validate JSON against these schemas using Python's built-in `json.tool`:

```bash
python -m json.tool schemas/proposal.schema.json > /dev/null && echo "Valid"
```

For runtime validation, use a JSON Schema library compatible with draft 2020-12.

## Relationship to SPEC.md

These schemas formalize the interfaces defined in [SPEC.md](../SPEC.md). The specification describes the full system; these schemas provide machine-readable definitions for the data structures.
