# Security and privacy

This is a single-user local application. Keep it bound to 127.0.0.1; it is not
configured for public hosting. API keys belong in .env and service-account
files in credentials/. Profiles, resumes and generated documents stay local
unless sent to the services used by the feature you run.

Scoring and drafting send profile/resume text and job descriptions to
Anthropic. Job searches contact enabled job boards and optionally Apify.
Matches are written to your Google Sheet; optional Telegram notifications
send job summaries to your configured chat. Configure your own accounts.

Do not publish sensitive details in a public issue. Use the hosting platform's
private vulnerability reporting feature if the repository owner enables it.
If credentials have been exposed, revoke or rotate them with their provider;
removing a file from a newer commit does not invalidate an exposed credential.

The release check is a basic guard, not a guarantee: manually review templates,
comments, document metadata, screenshots, and every file before publishing.
