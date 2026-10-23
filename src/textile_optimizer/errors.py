"""Application exception hierarchy.

Categories follow technical_specification 14.1 so the UI can show a specific message
for each kind of failure.
"""

from __future__ import annotations


class TextileOptimizerError(Exception):
    """Base class for all expected application errors."""


class InputValidationError(TextileOptimizerError):
    """Input data is malformed or inconsistent. ``messages`` lists actionable problems."""

    def __init__(self, messages: list[str] | str):
        if isinstance(messages, str):
            messages = [messages]
        self.messages = list(messages)
        super().__init__("; ".join(self.messages))


class PersistenceError(TextileOptimizerError):
    """A database operation failed (the transaction was rolled back)."""


class IntegrityConflictError(TextileOptimizerError):
    """An operation would break referential integrity (e.g. deleting a referenced machine)."""


class ModelConstructionError(TextileOptimizerError):
    """The scheduling model could not be constructed."""


class SolverExecutionError(TextileOptimizerError):
    """The solver raised an unexpected exception."""


class RunInProgressError(TextileOptimizerError):
    """A scheduling run is already executing (duplicate-run prevention)."""


class ExportError(TextileOptimizerError):
    """Report or export generation failed."""
