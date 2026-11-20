"""One error type with a code an agent can act on, and one exit code per kind of failure."""
from __future__ import annotations

EXIT = {"ok": 0, "internal": 1, "usage": 2, "invalid": 2, "confirm": 3, "refused": 4, "backend": 5, "unreachable": 5,
        "not_found": 6, "tampered": 6, "out_of_date": 6, "verify_failed": 7}
MEANING = {0: "done",
           1: "a bug in the command line, or the audit log could not be written: the message says which",
           2: "the command or its options were wrong",
           3: "destructive: dry-run it, ask the person, rerun with --yes",
           4: "refused: a host not allowed, plain http to another machine, a redirect, or credentials the server rejected",
           5: "the server failed or did not answer",
           6: "not found, nothing to undo, or a check failed (audit log, skill file)",
           7: "requests verify: the count was not what was expected"}


class HarnessError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint

    @property
    def exit(self) -> int:
        return EXIT.get(self.code, 1)

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **({"hint": self.hint} if self.hint else {})}
