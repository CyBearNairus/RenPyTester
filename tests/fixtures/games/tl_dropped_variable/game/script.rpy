# Fixture: a translation that leaves out a variable the original shows (spec TL-006).

define config.name = "Dropped Variable Fixture"

define g = Character("Guide")

default score = 3

label start:
    g "You have [score] points."

    g "That is all."

    return
