# Fixture: an exception the game handles itself must not be reported (spec ERR-011).

define config.name = "Caught Exception Fixture"

default outcome = ""

label start:
    python:
        try:
            undefined_function()
        except NameError:
            outcome = "handled"

    "The game [outcome] it."

    return
