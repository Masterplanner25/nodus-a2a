# Contributing to nodus-a2a

## Setup

```bash
git clone https://github.com/Masterplanner25/nodus-a2a.git
cd nodus-a2a
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/ -q
```

## Code style

- Python 3.11+
- No external dependencies in the main package (stdlib only)
- Type hints on all public functions
- Tests live in `tests/test_a2a.py`

## Submitting changes

1. Fork the repo and create a branch from `main`
2. Add tests for any new behaviour
3. Ensure `pytest tests/ -q` passes
4. Open a pull request with a clear description of what changes and why
