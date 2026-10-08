"""Builds the list of enabled JobSource objects from config/search.yaml."""

from __future__ import annotations

from .arbeitnow import ArbeitnowSource
from .apify_source import ApifySource
from .base import JobSource
from .remoteok import RemoteOKSource
from .remotive import RemotiveSource
from .weworkremotely import WeWorkRemotelySource


def build_sources(config) -> list[JobSource]:
    """Return one source object per enabled board in search.yaml."""
    enabled = config.enabled_sources()
    apify_cfg = config.apify()
    search_terms = [t for t in (apify_cfg.get("search_terms") or []) if t]

    sources: list[JobSource] = []

    if enabled.get("remoteok"):
        sources.append(RemoteOKSource(config))
    if enabled.get("arbeitnow"):
        sources.append(ArbeitnowSource(config))
    if enabled.get("remotive"):
        sources.append(RemotiveSource(config, search_terms=search_terms))
    if enabled.get("weworkremotely"):
        sources.append(WeWorkRemotelySource(config))

    if enabled.get("linkedin"):
        sources.append(
            ApifySource(config, "linkedin", apify_cfg.get("linkedin_actor", ""))
        )
    if enabled.get("upwork"):
        sources.append(
            ApifySource(config, "upwork", apify_cfg.get("upwork_actor", ""))
        )

    return sources
