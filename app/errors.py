from __future__ import annotations


class UserVisibleError(Exception):
    def __init__(self, message: str, *, category: str = "application_error"):
        super().__init__(message)
        self.message = message
        self.category = category
