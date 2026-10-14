# Generated coverage dashboard

`scripts/coverage_dashboard.py` writes `coverage_dashboard.html` here from the
historical database tables. The HTML is a local generated artifact, ignored by
Git; it is not a new technical-catalog benchmark or a committed result.

Run from the repository root:

```bash
PYTHONPATH=src .venv/bin/python scripts/coverage_dashboard.py
```

The existing dashboard was moved here without refreshing its recorded data.
See the [evaluation guide](../../docs/guides/evaluation.md).
