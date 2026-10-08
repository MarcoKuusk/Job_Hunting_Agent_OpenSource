# Contributor instructions

This repository contains generic software only. Do not add personal data,
credentials, local account identifiers, private paths, resumes, or application
outputs. Real configuration belongs in ignored config/profile.yaml and
config/search.yaml; tracked example files must remain generic.

Before staging or committing, inspect git status and the staged diff, then run
python scripts/check_public_release.py. Never print secret values in reports.
Run python -m unittest discover -s tests for code changes.

Preserve application behavior and human control: drafting is permitted, but
never automatically submit an application or email. Keep localhost binding,
lazy dependency imports in pure modules, existing sheet column ordering, and
all successfully scored jobs regardless of shortlist threshold.
