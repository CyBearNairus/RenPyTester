# Fixture: a script that does not parse (spec ERR-001).

define config.name = "Parse Error Fixture"

label start:
    "Before the bug."

    menu
        "A menu statement needs a colon."
