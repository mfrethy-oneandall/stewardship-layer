# Contributing

Thank you for your interest in contributing to the Stewardship Layer.

## Reporting Issues

- **Bugs**: Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md)
- **Features**: Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md)
- **Security**: See [SECURITY.md](SECURITY.md) for vulnerability reporting

## Pull Request Guidelines

1. **Fork and branch**: Create a feature branch from `main`
2. **Keep changes focused**: One logical change per PR
3. **Add tests**: New functionality requires tests
4. **Update docs**: If behavior changes, update relevant documentation
5. **Follow style**: See Code Style below

## Code Style

- **No external dependencies**: stdlib only (no pytest, ruff, etc.)
- **Type hints**: Use type annotations for function signatures
- **Docstrings**: Brief docstrings for public functions
- **Tests**: Use `unittest` from the standard library

## Running Tests

```bash
python -m unittest discover -s REFERENCE_IMPL/python/tests -v
```

All tests must pass before a PR will be merged.

## Review Process

The maintainer reviews all PRs. See [GOVERNANCE.md](GOVERNANCE.md) for decision-making details.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
