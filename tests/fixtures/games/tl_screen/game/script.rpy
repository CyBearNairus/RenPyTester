# Fixture: the about screen can be shown in the game's own language, but its Portuguese
# translation uses a variable that the game does not have (spec UI-002).
# Original content written for RenPyTester's tests.

define config.name = "Translated Screen Fixture"

define g = Character("Guide")
define studio = "Lantern Works"

label start:
    g "Welcome."
    return
