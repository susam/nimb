Release Checklist
=================

- Update version in `pyproject.toml`.

- Update `CHANGES.md`.

- Run the following commands:

  ```
  make checks

  git add -p
  git status
  git commit
  git push origin main

  make dist upload verify-upload

  VER=$(grep version pyproject.toml | cut -d '"' -f2)
  git tag $VER -m "NIMB $VER"
  git push origin $VER
  ```
