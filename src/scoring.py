"""Scores a job against your CV + profile using Claude (Anthropic).

Uses the Claude API's structured-output feature (a json_schema output format)
so the model returns clean JSON (a score 0-100, a recommendation, and reasons)
instead of free text we'd have to parse fragilely. Plain request (no
sampling/thinking params) so it works on whatever model you set in
config/search.yaml.
"""

from __future__ import annotations

import json
from typing import Any

from .config import scrub
from .models import Job

SYSTEM_PROMPT = (
    "You are a careful job-matching assistant helping a candidate decide which "
    "remote jobs are worth applying to. Given the candidate's CV and profile "
    "and a single job posting, judge how well the job fits the candidate. "
    "Reward genuine matches in role, seniority, skills, and stated "
    "requirements; penalise mismatches and anything on the candidate's avoid "
    "list. Be honest and a little strict — a high score should mean 'clearly "
    "worth applying to'."
)

# Structured-output schema. Note: numeric min/max constraints aren't supported
# by structured outputs, so we clamp the score to 0-100 in code afterward.
SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {
            "type": "integer",
            "description": "Fit from 0 (no match) to 100 (excellent match).",
        },
        "recommendation": {
            "type": "string",
            "enum": ["strong", "maybe", "skip"],
        },
        "reasons": {
            "type": "string",
            "description": "1-3 short sentences explaining the score.",
        },
    },
    "required": ["score", "recommendation", "reasons"],
    "additionalProperties": False,
}


def profile_to_text(profile: dict[str, Any]) -> str:
    """Render the profile.yaml dict into a readable block for the prompt."""
    lines: list[str] = []
    if profile.get("name"):
        lines.append(f"Name: {profile['name']}")
    if profile.get("location"):
        lines.append(f"Location: {profile['location']}")
    if profile.get("summary"):
        lines.append(f"Summary: {profile['summary']}")
    if profile.get("target_roles"):
        lines.append("Target roles: " + ", ".join(profile["target_roles"]))
    if profile.get("skills"):
        lines.append("Skills: " + ", ".join(profile["skills"]))
    req = profile.get("requirements") or {}
    if req:
        if req.get("remote_only"):
            lines.append("Requires: remote only")
        if req.get("min_salary"):
            lines.append(f"Minimum salary: {req['min_salary']}")
        if req.get("locations_allowed"):
            allowed = [a for a in req["locations_allowed"] if a]
            if allowed:
                lines.append("Can work from: " + ", ".join(allowed))
    if profile.get("avoid"):
        avoid = [a for a in profile["avoid"] if a]
        if avoid:
            lines.append("Avoid: " + ", ".join(avoid))
    return "\n".join(lines)


def build_client(api_key: str | None = None):
    """Create the Anthropic client (reads ANTHROPIC_API_KEY from env)."""
    import anthropic

    return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()


def score_job(job: Job, cv_text: str, profile_text: str, model: str,
              client=None) -> Job:
    """Score one job in place and return it. On API error the score is left
    as None and a (secret-scrubbed) note is stored in `job.reasons`."""
    client = client or build_client()

    user_prompt = (
        "CANDIDATE PROFILE:\n"
        f"{profile_text}\n\n"
        "CANDIDATE CV:\n"
        f"{cv_text}\n\n"
        "JOB POSTING:\n"
        f"{job.to_compact_text()}\n\n"
        "Score this job for this candidate."
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": SCORE_SCHEMA,
                },
            },
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("model declined to score this job")
        # With output_config.format the first text block is guaranteed valid JSON.
        text = next(b.text for b in resp.content if b.type == "text")
        data = json.loads(text)
        job.score = max(0, min(100, int(data.get("score", 0))))
        job.recommendation = str(data.get("recommendation", ""))
        job.reasons = str(data.get("reasons", ""))
    except Exception as exc:  # noqa: BLE001 — keep one bad job from killing the run
        job.score = None
        job.reasons = "Scoring failed: " + scrub(str(exc))
    return job
