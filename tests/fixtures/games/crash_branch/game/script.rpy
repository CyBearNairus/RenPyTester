# Fixture: one branch kills the engine outright; the others must still be explored (spec RUN-012).

define config.name = "Crash Branch Fixture"

label start:
    "Three doors."

    menu:
        "Trapdoor":
            python:
                import os
                os._exit(7)

        "Broken door":
            $ undefined_function()

        "Good door":
            "You made it."

    return
