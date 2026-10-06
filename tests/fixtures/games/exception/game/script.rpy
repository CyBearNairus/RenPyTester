# Fixture: an uncaught exception at a known line (spec ERR-002).

define config.name = "Exception Fixture"

label start:
    "Before the bug."

    jump chapter_two

label chapter_two:
    "About to break."

    $ undefined_function()

    "Never shown."

    return
