# eval-preflight

A pre-flight check for eval results. It catches partial runs, failed judges, mislabelled scores and
inconsistent aggregation, so the number you gate on is the number your eval actually produced.

**Status: alpha, pre-release (0.0.1). Not published to PyPI.** The full README arrives with 0.1.0;
[SPEC.md](SPEC.md) is the contract.

## What works today

- The generic input format ([docs/input-format.md](docs/input-format.md)), JSON or JSONL.
- Four checks ([docs/checks.md](docs/checks.md)): `task-failures`, `evaluator-coverage`,
  `evaluator-errors`, `name-collision`.
- `eval-preflight check RESULTS`: exit `0` on PASS or WARN, `1` on FAIL, `2` on a usage error.

```console
$ uv run eval-preflight check tests/fixtures/name_shift.json
```

## Development

```console
$ uv sync
$ make check   # ruff, ruff format --check, mypy --strict, pytest with coverage >= 95%
```
