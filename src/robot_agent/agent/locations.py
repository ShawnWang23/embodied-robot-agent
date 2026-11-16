"""Resolve semantic indoor locations to validated map poses."""

from __future__ import annotations

import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from robot_agent.core.exceptions import PlanValidationError


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=100)
    aliases: list[str] = Field(default_factory=list)
    x: float
    y: float
    yaw: float = Field(default=0.0, ge=-math.pi, le=math.pi)
    fallback_location: str | None = Field(default=None, max_length=100)

    @field_validator("x", "y", "yaw")
    @classmethod
    def require_finite_pose(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("location pose values must be finite")
        return value


class LocationCatalog:
    """Exact alias catalog; deliberately avoids unsafe fuzzy coordinates."""

    def __init__(self, locations: list[Location]) -> None:
        if not locations:
            raise ValueError("location catalog cannot be empty")
        self._locations = locations
        self._canonical = {location.name: location for location in locations}
        if len(self._canonical) != len(locations):
            raise ValueError("location names must be unique")
        self._lookup: dict[str, Location] = {}
        for location in locations:
            for candidate in [location.name, *location.aliases]:
                key = candidate.strip().casefold()
                if not key:
                    raise ValueError("location names and aliases cannot be empty")
                if key in self._lookup:
                    raise ValueError(f"duplicate location alias: {candidate}")
                self._lookup[key] = location
        for location in locations:
            if (
                location.fallback_location is not None
                and location.fallback_location not in self._canonical
            ):
                raise ValueError(
                    f"unknown fallback location '{location.fallback_location}' "
                    f"for '{location.name}'"
                )
            if location.fallback_location == location.name:
                raise ValueError(
                    f"location '{location.name}' cannot fall back to itself"
                )

    @classmethod
    def from_json(cls, path: str | Path) -> "LocationCatalog":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        locations = TypeAdapter(list[Location]).validate_python(raw)
        return cls(locations)

    @property
    def locations(self) -> tuple[Location, ...]:
        return tuple(self._locations)

    def resolve(self, name: str) -> Location:
        location = self._lookup.get(name.strip().casefold())
        if location is None:
            allowed = ", ".join(item.name for item in self._locations)
            raise PlanValidationError(
                f"Unknown location '{name}'. Allowed locations: {allowed}"
            )
        return location

    def planner_description(self) -> str:
        lines = []
        for location in self._locations:
            aliases = ", ".join(location.aliases) or "none"
            lines.append(f"- {location.name} (aliases: {aliases})")
        return "\n".join(lines)

    def fallback_for(self, location: Location) -> Location | None:
        """Return an explicitly configured fallback; never infer one geometrically."""

        if location.fallback_location is None:
            return None
        return self._canonical[location.fallback_location]

