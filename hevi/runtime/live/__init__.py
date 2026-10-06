"""HEVI P9.0 — Live provider observation.

P8.1 established that observing a provider is a third question, separate from what it
is and whether it may be used. This package fills that question with evidence that a
**real** endpoint answered.

    ProviderRuntimeStatus   we asked, here is the answer   (declared mechanism)
    LiveRuntimeStatus       we asked a real provider       (real answer)

Neither carries ``locality``, ``license_class`` or ``capabilities``: a provider that
answers does not thereby become local, licensed or approved.
"""

from hevi.runtime.live.credentials import (
    Credential,
    CredentialMissing,
    CredentialProvider,
    EnvironmentCredentialProvider,
    StaticCredentialProvider,
)
from hevi.runtime.live.drivers import (
    DriverRegistry,
    DriverResult,
    HttpLiveDriver,
    LocalLiveDriver,
    QueueLiveDriver,
    default_registry,
    redact,
)
from hevi.runtime.live.status import LiveOutcome, LiveRuntimeStatus

__all__ = [
    "Credential",
    "CredentialMissing",
    "CredentialProvider",
    "DriverRegistry",
    "DriverResult",
    "EnvironmentCredentialProvider",
    "HttpLiveDriver",
    "LiveOutcome",
    "LiveRuntimeStatus",
    "LocalLiveDriver",
    "QueueLiveDriver",
    "StaticCredentialProvider",
    "default_registry",
    "redact",
]
