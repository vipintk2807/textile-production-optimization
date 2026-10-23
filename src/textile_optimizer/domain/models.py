"""Input records (what the planner enters and what SQLite stores).

These Pydantic models validate *field-level* rules. Cross-record rules (references,
cycles, eligibility, calendars) live in ``validation.input_validation`` so that the same
checks run for forms, stored data and test fixtures.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .. import config

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")
ID_HELP = "1-64 characters: letters, digits, '.', '_' or '-', starting with a letter or digit."


class OrderStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


class MachineStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class OperationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class Objective(StrEnum):
    MAKESPAN = "makespan"
    TOTAL_TARDINESS = "total_tardiness"
    WEIGHTED_TARDINESS = "weighted_tardiness"


OBJECTIVE_LABELS = {
    Objective.MAKESPAN: "Minimize makespan",
    Objective.TOTAL_TARDINESS: "Minimize total tardiness",
    Objective.WEIGHTED_TARDINESS: "Minimize weighted total tardiness",
}


def _check_id(value: str, what: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{what} is required.")
    if not ID_PATTERN.match(value):
        raise ValueError(f"{what} '{value}' is invalid. {ID_HELP}")
    return value


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)


class OrderRecord(_Record):
    order_id: str
    product_code: str
    description: str = ""
    quantity: float
    quantity_unit: str
    release_time: int
    due_time: int
    priority: int | None = None
    weight: int | None = None
    status: OrderStatus = OrderStatus.DRAFT
    notes: str = ""
    is_synthetic: bool = False

    @field_validator("order_id")
    @classmethod
    def _order_id(cls, v: str) -> str:
        return _check_id(v, "Order ID")

    @field_validator("product_code")
    @classmethod
    def _product(cls, v: str) -> str:
        v = _clean_text(v)
        if not v:
            raise ValueError("Product code is required.")
        return v

    @field_validator("description", "notes")
    @classmethod
    def _text(cls, v: str) -> str:
        return _clean_text(v)

    @field_validator("quantity")
    @classmethod
    def _quantity(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0:
            raise ValueError("Quantity must be a positive number.")
        return v

    @field_validator("quantity_unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        v = _clean_text(v)
        if v not in config.QUANTITY_UNITS:
            raise ValueError(
                f"Quantity unit '{v}' is not supported. Choose one of: {', '.join(config.QUANTITY_UNITS)}."
            )
        return v

    @field_validator("release_time", "due_time")
    @classmethod
    def _time(cls, v: int) -> int:
        if v < 0 or v > config.MAX_HORIZON_MINUTES:
            raise ValueError("Times must be whole minutes from the planning origin (>= 0).")
        return v

    @field_validator("priority")
    @classmethod
    def _priority(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 5:
            raise ValueError("Priority must be between 1 (lowest) and 5 (highest), or empty.")
        return v

    @field_validator("weight")
    @classmethod
    def _weight(cls, v: int | None) -> int | None:
        if v is not None and not 0 <= v <= 1_000_000:
            raise ValueError("Weight must be a non-negative whole number (<= 1,000,000), or empty.")
        return v

    @model_validator(mode="after")
    def _due_after_release(self) -> OrderRecord:
        if self.due_time < self.release_time:
            raise ValueError("Due time must not be earlier than the release time.")
        return self


class IntervalRecord(_Record):
    start: int
    end: int

    @model_validator(mode="after")
    def _valid(self) -> IntervalRecord:
        if self.start < 0:
            raise ValueError("Interval start must be >= 0.")
        if self.end <= self.start:
            raise ValueError(f"Interval [{self.start}, {self.end}) is invalid: end must be after start.")
        return self

    def as_tuple(self) -> tuple[int, int]:
        return (self.start, self.end)


class MachineRecord(_Record):
    machine_id: str
    machine_name: str
    machine_type: str
    supported_processes: list[str]
    status: MachineStatus = MachineStatus.ACTIVE
    notes: str = ""
    availability: list[IntervalRecord] = []
    downtime: list[IntervalRecord] = []
    is_synthetic: bool = False

    @field_validator("machine_id")
    @classmethod
    def _machine_id(cls, v: str) -> str:
        return _check_id(v, "Machine ID")

    @field_validator("machine_name", "machine_type")
    @classmethod
    def _required_text(cls, v: str) -> str:
        v = _clean_text(v)
        if not v:
            raise ValueError("This field is required.")
        return v

    @field_validator("notes")
    @classmethod
    def _notes(cls, v: str) -> str:
        return _clean_text(v)

    @field_validator("supported_processes")
    @classmethod
    def _processes(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in v:
            item = _clean_text(item)
            if item and item not in cleaned:
                cleaned.append(item)
        if not cleaned:
            raise ValueError("At least one supported process (capability) is required.")
        return cleaned


class EligibleMachine(_Record):
    machine_id: str
    duration_override: int | None = None

    @field_validator("duration_override")
    @classmethod
    def _override(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("A machine-specific duration must be a positive whole number.")
        return v


class OperationRecord(_Record):
    operation_id: str
    order_id: str
    operation_name: str
    sequence: int = 1
    processing_duration: int
    duration_is_estimate: bool = True
    duration_source: str = ""
    eligible_machines: list[EligibleMachine] = []
    predecessors: list[str] = []
    changeover_category: str | None = None
    status: OperationStatus = OperationStatus.ACTIVE
    notes: str = ""
    is_synthetic: bool = False

    @field_validator("operation_id")
    @classmethod
    def _op_id(cls, v: str) -> str:
        return _check_id(v, "Operation ID")

    @field_validator("order_id")
    @classmethod
    def _order_ref(cls, v: str) -> str:
        return _check_id(v, "Parent order ID")

    @field_validator("operation_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = _clean_text(v)
        if not v:
            raise ValueError("Operation name / process category is required.")
        return v

    @field_validator("sequence")
    @classmethod
    def _sequence(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Sequence must be >= 0.")
        return v

    @field_validator("processing_duration")
    @classmethod
    def _duration(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Processing duration must be a positive whole number of minutes.")
        if v > config.MAX_HORIZON_MINUTES:
            raise ValueError("Processing duration is unreasonably large.")
        return v

    @field_validator("duration_source", "notes")
    @classmethod
    def _text(cls, v: str) -> str:
        return _clean_text(v)

    @field_validator("changeover_category")
    @classmethod
    def _category(cls, v: str | None) -> str | None:
        v = _clean_text(v)
        return v or None

    @model_validator(mode="after")
    def _structure(self) -> OperationRecord:
        if self.operation_id in self.predecessors:
            raise ValueError(f"Operation {self.operation_id} cannot be its own predecessor.")
        if len(set(self.predecessors)) != len(self.predecessors):
            raise ValueError("Duplicate predecessor entries are not allowed.")
        ids = [m.machine_id for m in self.eligible_machines]
        if len(set(ids)) != len(ids):
            raise ValueError("A machine may appear only once in the eligible machine list.")
        return self

    def duration_on(self, machine_id: str) -> int | None:
        """Effective duration on a machine (override or the operation default)."""
        for em in self.eligible_machines:
            if em.machine_id == machine_id:
                return em.duration_override or self.processing_duration
        return None


class ChangeoverRule(_Record):
    from_category: str
    to_category: str
    minutes: int

    @field_validator("from_category", "to_category")
    @classmethod
    def _cat(cls, v: str) -> str:
        v = _clean_text(v)
        if not v:
            raise ValueError("Changeover categories are required.")
        return v

    @field_validator("minutes")
    @classmethod
    def _minutes(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Changeover duration must be >= 0 minutes.")
        return v


class PlanningSettings(_Record):
    origin: datetime = config.DEFAULT_ORIGIN
    horizon_end: int = config.DEFAULT_HORIZON_END_MINUTES
    objective: Objective = Objective.TOTAL_TARDINESS
    enforce_due_dates: bool = False
    changeover_enabled: bool = False
    time_limit_seconds: float = config.DEFAULT_TIME_LIMIT_SECONDS
    workers: int = config.DEFAULT_WORKERS
    random_seed: int = config.DEFAULT_SEED
    dataset_label: str = ""

    @field_validator("origin")
    @classmethod
    def _origin(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            raise ValueError("Planning origin must be a naive local datetime (no time zone).")
        return v.replace(second=0, microsecond=0)

    @field_validator("horizon_end")
    @classmethod
    def _horizon(cls, v: int) -> int:
        if not 1 <= v <= config.MAX_HORIZON_MINUTES:
            raise ValueError(f"Horizon end must be between 1 and {config.MAX_HORIZON_MINUTES} minutes.")
        return v

    @field_validator("time_limit_seconds")
    @classmethod
    def _limit(cls, v: float) -> float:
        if not (config.MIN_TIME_LIMIT_SECONDS <= v <= config.MAX_TIME_LIMIT_SECONDS):
            raise ValueError(
                f"Solver time limit must be between {config.MIN_TIME_LIMIT_SECONDS} and "
                f"{config.MAX_TIME_LIMIT_SECONDS} seconds."
            )
        return float(v)

    @field_validator("workers")
    @classmethod
    def _workers(cls, v: int) -> int:
        if not 1 <= v <= config.MAX_WORKERS:
            raise ValueError(f"Solver workers must be between 1 and {config.MAX_WORKERS}.")
        return v

    @field_validator("random_seed")
    @classmethod
    def _seed(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Random seed must be >= 0.")
        return v
