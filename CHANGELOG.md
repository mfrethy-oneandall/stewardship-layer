# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2025-02-02

### Added
- Initial release
- Core `StewardshipGate` implementation with five-step loop (Propose, Explain, Decide, Execute, Learn)
- Policy system: allowlist, safe domain, reversibility required
- Rate limiting support
- Append-only audit logging with trace IDs
- Reference implementation in Python (stdlib only, no dependencies)
- Unit tests using `unittest`
- Documentation: STEWARD.md, SPEC.md, PATTERNS.md
- JSON schemas for Proposal and Decision interfaces
- GitHub Actions CI workflow
- Governance documentation

[Unreleased]: https://github.com/mfrethy-oneandall/stewardship-layer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mfrethy-oneandall/stewardship-layer/releases/tag/v0.1.0
