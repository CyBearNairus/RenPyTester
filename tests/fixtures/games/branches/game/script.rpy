# Fixture: a crash that only one combination of choices reaches (spec EXP-001, EXP-004).

define config.name = "Branches Fixture"

label start:
    "A fork in the road."

    menu:
        "Left":
            "The left road is quiet."

        "Right":
            "The right road forks again."

            menu:
                "First":
                    "Nothing happens."

                "Second":
                    $ undefined_function()

    "The end."

    return
