# Fixture: a jump to a label that does not exist (spec ERR-002).

define config.name = "Bad Jump Fixture"

label start:
    "Before the bug."

    jump expression "no_such_" + "label"
