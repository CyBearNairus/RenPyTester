# Fixture: a label the story never reaches kills the engine outright; the labels after it must
# still be played (spec RUN-012, EXP-007).

define config.name = "Crash Label Fixture"

label start:
    "Nothing wrong here."
    return

label alpha:
    "Alpha is fine."
    return

label trap:
    python:
        import os
        os._exit(7)
    return

label zeta:
    $ missing_in_zeta()
    return
