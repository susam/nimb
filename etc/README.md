Release Checklist
=================

- Update version in `pyproject.toml`.

- Update `CHANGES.md`.

- Run the following commands:

  ```
  make checks
  make dist upload verify-upload
  ```
