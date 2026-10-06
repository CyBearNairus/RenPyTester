# Fixture: two crashes on different branches; both must be found in one run (spec RUN-011).

define config.name = "Two Bugs Fixture"

label start:
    menu:
        "Alpha":
            $ undefined_alpha()

        "Beta":
            $ undefined_beta()

        "Gamma":
            "This one is fine."

    return
