# Fixture: the about screen shows a picture whose file is not in the game (spec UI-001, ERR-003).
# Original content written for RenPyTester's tests.

define config.name = "Screen Missing Image Fixture"

define g = Character("Guide")

label start:
    g "The story is fine."
    return
