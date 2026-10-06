# Fixture: one branch never returns; the others must still be explored (spec RUN-008).

define config.name = "Hang Branch Fixture"

label start:
    "Three doors."

    menu:
        "Endless corridor":
            python:
                import time
                while True:
                    time.sleep(0.05)

        "Broken door":
            $ undefined_function()

        "Good door":
            "You made it."

    return
