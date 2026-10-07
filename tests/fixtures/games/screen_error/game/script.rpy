# Fixture: the preferences screen uses a variable that the game does not have (spec UI-001).
# Original content written for RenPyTester's tests.

define config.name = "Screen Error Fixture"

define g = Character("Guide")

label start:
    g "The story is fine."
    g "Nobody opens the preferences while it is played."
    return
