# Coverage scope

Coverage measures the `deopjufier` package only. Tests, reference checkouts,
downloaded samples, and generated outputs are excluded.

```bash
uv run pytest --cov=deopjufier --cov-branch --cov-report=term-missing
```

Coverage is a code-execution metric, not parser compatibility evidence. Format
support requires legal fixtures, exact source-range contracts, and independent
value checks.
