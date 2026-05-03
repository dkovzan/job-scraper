import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TelegramConfig:
    bot_token_env: str
    allowed_chats_env: str


@dataclass(frozen=True)
class StateConfig:
    seen_file: str
    subscriptions_file: str
    offset_file: str
    max_seen_ids: int


@dataclass(frozen=True)
class LocationClause:
    city: str | None
    country: str | None
    modes: tuple[str, ...]


@dataclass(frozen=True)
class DefaultsConfig:
    seniority: tuple[str, ...]
    locations: tuple[LocationClause, ...]


@dataclass(frozen=True)
class Config:
    telegram: TelegramConfig
    state: StateConfig
    defaults: DefaultsConfig


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"config: file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"config: invalid TOML in {path}: {e}") from e

    return Config(
        telegram=_parse_telegram(raw),
        state=_parse_state(raw),
        defaults=_parse_defaults(raw),
    )


def _require_section(raw: dict[str, Any], section: str) -> dict[str, Any]:
    if section not in raw:
        raise ValueError(f"config: missing section [{section}]")
    value = raw[section]
    if not isinstance(value, dict):
        raise ValueError(f"config: section [{section}] must be a table")
    return value


def _require_key(section: dict[str, Any], section_name: str, key: str) -> Any:
    if key not in section:
        raise ValueError(f"config: missing key '{key}' in [{section_name}]")
    return section[key]


def _parse_telegram(raw: dict[str, Any]) -> TelegramConfig:
    section = _require_section(raw, "telegram")
    return TelegramConfig(
        bot_token_env=_require_key(section, "telegram", "bot_token_env"),
        allowed_chats_env=_require_key(section, "telegram", "allowed_chats_env"),
    )


def _parse_state(raw: dict[str, Any]) -> StateConfig:
    section = _require_section(raw, "state")
    return StateConfig(
        seen_file=_require_key(section, "state", "seen_file"),
        subscriptions_file=_require_key(section, "state", "subscriptions_file"),
        offset_file=_require_key(section, "state", "offset_file"),
        max_seen_ids=int(_require_key(section, "state", "max_seen_ids")),
    )


def _parse_defaults(raw: dict[str, Any]) -> DefaultsConfig:
    section = _require_section(raw, "defaults")
    seniority = _require_key(section, "defaults", "seniority")
    locations_raw = _require_key(section, "defaults", "locations")
    if not isinstance(seniority, list):
        raise ValueError("config: defaults.seniority must be a list")
    if not isinstance(locations_raw, list):
        raise ValueError("config: defaults.locations must be a list")
    return DefaultsConfig(
        seniority=tuple(str(s) for s in seniority),
        locations=tuple(_parse_location(loc, i) for i, loc in enumerate(locations_raw)),
    )


def _parse_location(loc: Any, index: int) -> LocationClause:
    if not isinstance(loc, dict):
        raise ValueError(f"config: defaults.locations[{index}] must be a table")
    has_city = "city" in loc
    has_country = "country" in loc
    if not (has_city or has_country):
        raise ValueError(f"config: defaults.locations[{index}] must define 'city' or 'country'")
    modes = loc.get("modes", [])
    if not isinstance(modes, list):
        raise ValueError(f"config: defaults.locations[{index}].modes must be a list")
    return LocationClause(
        city=loc.get("city"),
        country=loc.get("country"),
        modes=tuple(str(m) for m in modes),
    )
