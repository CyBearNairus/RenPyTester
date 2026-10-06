# Fixture: a text prompt and a menu before a crash, to check that decisions are recorded (spec EXP-004).

define config.name = "Choices Fixture"

default player_name = ""

label start:
    $ player_name = renpy.input("Name?", length=11)

    "Hello, [player_name]."

    menu:
        "Left":
            $ undefined_function()
        "Right":
            "Fine."

    return
