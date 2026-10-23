"""Structured validation results shared by input validation and schedule validation."""

from __future__ import annotations

from dataclasses import dataclass, field

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" (blocking) or "warning"
    code: str
    message: str
    order_id: str | None = None
    operation_id: str | None = None
    machine_id: str | None = None
    interval: tuple[int, int] | None = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "order_id": self.order_id,
            "operation_id": self.operation_id,
            "machine_id": self.machine_id,
            "interval": list(self.interval) if self.interval else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Issue:
        iv = d.get("interval")
        return cls(
            d["severity"],
            d["code"],
            d["message"],
            d.get("order_id"),
            d.get("operation_id"),
            d.get("machine_id"),
            (iv[0], iv[1]) if iv else None,
        )


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    def add(self, severity: str, code: str, message: str, **refs) -> None:
        self.issues.append(Issue(severity, code, message, **refs))

    def error(self, code: str, message: str, **refs) -> None:
        self.add(ERROR, code, message, **refs)

    def warn(self, code: str, message: str, **refs) -> None:
        self.add(WARNING, code, message, **refs)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def passed(self) -> bool:
        return not self.errors

    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    def error_codes(self) -> set[str]:
        return {i.code for i in self.errors}
