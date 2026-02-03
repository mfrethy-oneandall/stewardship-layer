# Stewardship Layer

[![CI](https://github.com/mfrethy-oneandall/stewardship-layer/actions/workflows/ci.yaml/badge.svg)](https://github.com/mfrethy-oneandall/stewardship-layer/actions/workflows/ci.yaml)

A lightweight pattern and reference implementation for human-in-the-loop control of autonomous agents and automation. It packages a clear governance loop—Propose → Explain → Confirm → Execute → Learn—so teams can ship automation without surrendering agency.

## Table of Contents

- [Project Status](#project-status)
- [Why It Exists](#why-it-exists)
- [Who It's For](#who-its-for)
- [Quickstart](#quickstart)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Project Status

**Alpha** — The core loop is implemented and tested. APIs may change. Feedback welcome.

## Why It Exists

Automation systems and AI agents increasingly propose or execute actions with real-world consequences. This creates operational risk when:

- An agent proposes a destructive action without human review
- Audit trails are incomplete or missing
- There's no clear rollback path for failed actions
- Rate limits or blast radius controls don't exist

The stewardship layer addresses these by inserting a gate between intent and execution. Every action flows through Propose → Explain → Confirm → Execute → Learn. Humans retain final say. All decisions are logged.

**Concrete use cases:**

- CI/CD pipelines that require approval before deploying to production
- Home automation (Home Assistant, IoT) with confirmation before irreversible actions
- LLM agents that need human approval before executing tools
- Infrastructure automation with audit requirements

## Who It's For

- Engineers integrating LLM or rule-based agents with production systems
- SRE/Platform teams adding guardrails to automation (CI/CD, infrastructure, IoT)
- Security and risk teams needing auditability and reversible changes

## Quickstart

Requirements: Python 3.10+, no external packages.

```bash
git clone https://github.com/mfrethy-oneandall/stewardship-layer.git
cd stewardship-layer
python -m venv .venv
source .venv/bin/activate
python REFERENCE_IMPL/python/cli_demo.py
python -m unittest discover -s REFERENCE_IMPL/python/tests -v
```

## Documentation

- [STEWARD.md](STEWARD.md) — Behavior contract and five-step loop
- [SPEC.md](SPEC.md) — Full specification (actors, interfaces, state machine, threat model)
- [PATTERNS.md](PATTERNS.md) — Design patterns for stewardship
- [AGENT_SUMMARY.md](AGENT_SUMMARY.md) — Quick reference for agent integration
- [schemas/](schemas/) — JSON Schema definitions for Proposal and Decision

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Governance](GOVERNANCE.md)
- [Security Policy](SECURITY.md)

## License

[Apache 2.0](LICENSE)

---

Maintained by Mike Frethy ([@mfrethy-oneandall](https://github.com/mfrethy-oneandall))
