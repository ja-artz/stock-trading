"""Load strategy and universe configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_STRATEGY_PATH = PACKAGE_ROOT / "config" / "strategy.yaml"
DEFAULT_UNIVERSE_OVERRIDES_PATH = PACKAGE_ROOT / "config" / "universe.yaml"
DEFAULT_DB_PATH = Path("data/intraday_momentum/research.db")


@dataclass
class StrategyConfig:
    raw: dict[str, Any]
    strategy_path: Path

    @property
    def universe(self) -> dict[str, Any]:
        return self.raw.get("universe", {})

    @property
    def trigger(self) -> dict[str, Any]:
        return self.raw.get("trigger", {})

    @property
    def labels(self) -> dict[str, Any]:
        return self.raw.get("labels", {})

    @property
    def execution(self) -> dict[str, Any]:
        return self.raw.get("execution", {})

    @property
    def costs(self) -> dict[str, Any]:
        return self.raw.get("costs", {})

    @property
    def validation(self) -> dict[str, Any]:
        return self.raw.get("validation", {})

    @property
    def prototype(self) -> dict[str, Any]:
        return self.raw.get("prototype", {})

    @property
    def ingest(self) -> dict[str, Any]:
        return self.raw.get("ingest", {})


@dataclass
class UniverseOverrides:
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)
    overrides_path: Path = DEFAULT_UNIVERSE_OVERRIDES_PATH


def load_universe_overrides(path: Optional[Path | str] = None) -> UniverseOverrides:
    overrides_path = Path(path) if path else DEFAULT_UNIVERSE_OVERRIDES_PATH
    if not overrides_path.exists():
        return UniverseOverrides(overrides_path=overrides_path)
    with overrides_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    include = [str(t).upper() for t in raw.get("include", [])]
    exclude = [str(t).upper() for t in raw.get("exclude", [])]
    return UniverseOverrides(include=include, exclude=exclude, overrides_path=overrides_path)


# Backward-compatible alias
UniverseConfig = UniverseOverrides
load_universe = load_universe_overrides


def load_strategy(path: Optional[Path | str] = None) -> StrategyConfig:
    strategy_path = Path(path) if path else DEFAULT_STRATEGY_PATH
    with strategy_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return StrategyConfig(raw=raw, strategy_path=strategy_path)


def prototype_warnings(config: StrategyConfig) -> List[str]:
    warnings: List[str] = []
    proto = config.prototype
    if not proto.get("survivorship_safe", False):
        warnings.append("Universe is not survivorship-safe (prototype mode).")
    if proto.get("data_provider") == "yfinance":
        warnings.append(
            "yfinance provides ~7 calendar days per pull; archive grows via daily ingest."
        )
    if proto.get("spread_source") == "modeled":
        warnings.append("Spreads are modeled, not from NBBO quotes.")
    warnings.append("PROTOTYPE — not validation-grade; do not claim edge from this data.")
    return warnings
