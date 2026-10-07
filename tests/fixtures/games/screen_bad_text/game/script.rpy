# Fixture: the help screen has a text tag that is never closed (spec UI-001, ERR-005).
# Original content written for RenPyTester's tests.

define config.name = "Screen Bad Text Fixture"

define g = Character("Guide")

label start:
    g "The story is fine."
    return
