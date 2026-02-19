Run the full validation suite for the current state of the codebase:

1. **Lint**: `ruff check apex_brain scripts`
2. **Format**: `ruff format --check apex_brain scripts`
3. **Unit Tests**: `PYTHONPATH=apex_brain python -m pytest apex_brain/tests -v --tb=short`
4. **Secret Scan**: `gitleaks detect --source . --verbose` (if available, otherwise skip)

Report all results. If anything fails, list the failures and suggest fixes. Do NOT mark any task as complete if validation fails.
