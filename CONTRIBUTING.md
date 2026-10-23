# Contributing

1. Create a virtual environment and `pip install -r requirements-dev.txt`.
2. Read `docs/ASSUMPTIONS_AND_LIMITATIONS.md`: every new constraint needs a documented rule, a model formulation, **independent validator** support and tests (including a negative test).
3. Run `python -m pytest`, `python -m ruff check .` and `python -m ruff format --check .` before opening a pull request.
4. Never commit real production data, databases, logs or credentials. Sample data must be labelled synthetic.
5. Do not weaken or delete tests to obtain a pass; update the requirement and the test together.
