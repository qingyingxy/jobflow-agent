"""Separate interrupted work and provider outages from failed interpretations."""

from datetime import timedelta
from time import monotonic

DEFERRED = {"semantic_budget", "semantic_pending", "semantic_cancelled", "semantic_unavailable"}
PROVIDER_ERRORS = {"model_unavailable", "semantic_provider_cooldown"}
_providers = {}


def failed_attempt(error):
    return bool(error and error not in DEFERRED | PROVIDER_ERRORS)


def retry_at(error, failures, now):
    if error in PROVIDER_ERRORS:
        return (now + timedelta(seconds=60)).isoformat()
    if failed_attempt(error):
        return (now + timedelta(seconds=60 if failures < 2 else 300)).isoformat()
    return None


def provider_key(settings, client):
    # Test/custom clients are isolated; real workers share their provider's
    # cooldown across batches. No credentials participate in diagnostics.
    return client if client is not None else (settings.structured_model_provider, settings.llm_base_url, settings.llm_model)


def provider_cooling(key):
    return _providers.get(key, (0, 0))[1] > monotonic()


def provider_result(key, error):
    if error is None:
        _providers.pop(key, None)
    elif error in PROVIDER_ERRORS:
        failures = _providers.get(key, (0, 0))[0] + 1
        _providers[key] = (failures, monotonic() + 60 if failures >= 3 else 0)
