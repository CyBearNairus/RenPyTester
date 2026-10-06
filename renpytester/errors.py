"""Errors that stop a run and are shown to the user as a translated message."""


class ToolError(Exception):
    """A problem that prevents testing, described by a message identifier and its parameters.

    These map to exit code 3 (spec CLI-003), except UsageError.
    """

    exit_code = 3

    def __init__(self, message_id, **params):
        super().__init__(message_id)
        self.message_id = message_id
        self.params = params


class UsageError(ToolError):
    """Bad command line or configuration: exit code 2."""

    exit_code = 2
