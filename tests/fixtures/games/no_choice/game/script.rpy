# Fixture: a menu where every choice is switched off (spec ERR-008).

define config.name = "No Choice Fixture"

default has_key = False
default has_coin = False

label start:
    "A locked door."

    menu:
        "Use the key" if has_key:
            "It opens."

        "Pay the guard" if has_coin:
            "He lets you through."

    "Nobody can get past this point the way the author meant."

    return
