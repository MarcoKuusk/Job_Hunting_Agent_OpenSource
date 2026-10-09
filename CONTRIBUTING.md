# Contributing

Use Python 3.11 or newer and install requirements.txt in a virtual environment.
Run `python -m unittest discover -s tests` before submitting changes.
Run `python scripts/check_public_release.py` before committing.

Keep personal settings in config/profile.yaml and config/search.yaml. Only
fictional examples belong in tracked .example.yaml files. Do not attach real
resumes, generated applications, logs, screenshots with personal data,
service-account JSON, or .env files to issues or pull requests.

Preserve the human-controlled application flow: never submit applications or
send application emails automatically. Keep the Flask app bound to localhost.
