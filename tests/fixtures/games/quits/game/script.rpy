# Fixture: a game that closes itself at the end (spec RUN-007).

define config.name = "Quit Fixture"

label start:
    "Goodbye."

    $ renpy.quit()
