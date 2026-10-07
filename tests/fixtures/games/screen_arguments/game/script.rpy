# Fixture: a game with nothing wrong, whose save screen asks for a value of its own (spec UI-001).
# Original content written for RenPyTester's tests.

define config.name = "Screen Arguments Fixture"

define g = Character("Guide")

label start:
    g "The story is fine."
    return
