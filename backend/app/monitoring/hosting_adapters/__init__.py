"""Hosting provider adapters.

Every adapter declares what it can retrieve and how it authenticates. Adapters only call
documented, authorized provider APIs; they never scrape dashboards or log in as a user.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.monitoring.types import CheckError, CheckErrorCode, LookupResult


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    required: bool = True
    help: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "required": self.required, "help": self.help}


@dataclass(frozen=True)
class AdapterContext:
    config: dict
    secrets: dict
    external_ref: str | None


class HostingAdapter(ABC):
    key: str
    label: str
    description: str
    auth_method: str
    supported_fields: tuple[str, ...]
    config_fields: tuple[FieldSpec, ...] = ()
    secret_fields: tuple[FieldSpec, ...] = ()
    requires_external_ref: bool = True
    # Requests per minute the adapter will make against a provider (enforced by http.throttle).
    rate_limit_per_minute: int = 30
    timeout_seconds: float = 15.0
    max_retries: int = 3

    def validate_config(self, config: dict, secrets: dict) -> None:
        for spec in self.config_fields:
            if spec.required and not str(config.get(spec.key) or "").strip():
                raise CheckError(CheckErrorCode.CONFIG_ERROR, f"Integration setting '{spec.label}' is required.")
        for spec in self.secret_fields:
            if spec.required and not str(secrets.get(spec.key) or "").strip():
                raise CheckError(CheckErrorCode.CONFIG_ERROR, f"Integration secret '{spec.label}' is not set.")

    @abstractmethod
    def check(self, ctx: AdapterContext) -> LookupResult: ...

    @abstractmethod
    def test_connection(self, ctx: AdapterContext) -> str: ...

    def info(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "auth_method": self.auth_method,
            "supported_fields": list(self.supported_fields),
            "config_fields": [f.as_dict() for f in self.config_fields],
            "secret_fields": [f.as_dict() for f in self.secret_fields],
        }


_REGISTRY: dict[str, HostingAdapter] = {}


def register(adapter: HostingAdapter) -> HostingAdapter:
    _REGISTRY[adapter.key] = adapter
    return adapter


def get_adapter(key: str) -> HostingAdapter:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise CheckError(CheckErrorCode.UNSUPPORTED, f"Unknown hosting adapter '{key}'.") from None


def all_adapters() -> list[HostingAdapter]:
    return sorted(_REGISTRY.values(), key=lambda a: a.label)


# Import adapters so they register themselves.
from app.monitoring.hosting_adapters import json_api, whmcs  # noqa: E402,F401
