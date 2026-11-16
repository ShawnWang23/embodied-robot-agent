"""Project-specific errors with clear ownership boundaries."""


class RobotAgentError(Exception):
    """Base class for expected project errors."""


class TaskNotFoundError(RobotAgentError):
    """Raised when a requested task ID does not exist."""


class InvalidTaskStateError(RobotAgentError):
    """Raised when an operation is invalid for the task's current state."""


class PlanningError(RobotAgentError):
    """Raised when a planner cannot produce a complete structured plan."""


class PlanValidationError(RobotAgentError):
    """Raised when a generated plan is unsafe or not executable."""

