# Contributing to agent-vcr

Thanks for your interest in contributing. Issues, discussions, and pull
requests are all welcome.

## Development setup

```bash
git clone https://github.com/JaydenCJ/agent-vcr
cd agent-vcr
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the checks

```bash
pytest                 # unit tests + example tests (tests/ and examples/)
bash scripts/smoke.sh  # end-to-end smoke: record, replay, CLI diff
```

Both must pass before a pull request is reviewed. The test suite runs fully
offline and needs no API keys.

## Ground rules

- **No new runtime dependencies.** The core package is standard-library only;
  that is a feature. Test-only dependencies belong in the `dev` extra.
- **Cassette format changes need a version bump and docs.** Anything that
  changes the meaning of an existing field must bump `CASSETTE_VERSION` and
  update `docs/cassette-format.md` in the same pull request.
- **Every public API needs an English docstring and a test.** The README
  quickstart example is executed verbatim by
  `tests/test_readme_example.py`, so keep code and docs in sync.
- **Keep the three READMEs aligned.** `README.md`, `README.zh.md`, and
  `README.ja.md` share the same structure; update all three when you change
  one (English is the authoritative version).

## Reporting bugs

Please include the cassette (redacted output is safe to share by design), the
mode you ran in, and the full error message — `CassetteMissError` diffs are
usually enough to diagnose a mismatch.
