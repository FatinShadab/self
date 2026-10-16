# Contributing to SELF

Thanks for taking an interest in SELF. Contributions are welcome, including
bug fixes, tests, documentation, safety improvements, and experiments that
make the runtime easier to understand and operate.

## Before opening an issue or pull request

- Search existing issues and pull requests first.
- For security-sensitive reports, follow [SECURITY.md](SECURITY.md) instead of
  opening a public issue.
- Do not include API keys, credentials, personal data, or generated runtime
  state from `workspace/` in a report or patch.
- For larger changes, open an issue first so the design and scope can be
  discussed.

## Development setup

SELF is developed and tested in Docker. From the repository root:

```powershell
.\scripts\run-tests.ps1
```

On a Unix shell, use `bash scripts/run-tests.sh`. The scripts build the
image and run both the harness and eval-only suites without starting the
agent or requiring provider credentials. Do not add
real credentials to `.env.example`, source files, tests, or logs.

## Python documentation

Follow PEP 257 for module, class, and public function or method docstrings.
Start with a short summary ending in a period; describe functions as actions
and classes by their responsibility. Add a blank line after a class docstring.
For APIs with non-obvious inputs, results, side effects, or safety boundaries,
add a short paragraph or labeled `Args` and `Returns` sections. Keep
docstrings accurate when behavior changes.

Run `python scripts/check_docstrings.py` to check documentation coverage.
The check uses the Python standard library and does not call a model.

## Making changes

1. Create a focused branch from `main`.
2. Add or update tests for behavior changes.
3. Keep changes small and explain operational or security consequences.
4. Run the test suite and, when relevant, the Phase 7/8 verification scripts.
5. Update the README or other documentation when user-visible behavior
   changes.
6. Open a pull request using the repository template.

Generated state under `workspace/` is intentionally ignored. The container is
allowed to run as root inside its own namespace and may execute generated code;
changes that affect this boundary need especially clear documentation and
tests. Do not weaken the documented human-review gates or secret redaction
without explaining why.

## Pull requests

A maintainer may ask for revisions, documentation, tests, or a narrower scope.
Please keep review discussion constructive and follow the [Code of Conduct](CODE_OF_CONDUCT.md).

By submitting a contribution, you agree that it may be distributed under the
project's [MIT License](LICENSE).
