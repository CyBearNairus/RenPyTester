# Fixture: a small game with no bugs. Original content written for RenPyTester's tests.

define config.name = "Clean Fixture"
define config.version = "1.0"

define g = Character("Guide")

default visits = 0
default player_name = ""

label start:
    scene black
    with dissolve

    g "This game has nothing wrong with it."

    $ player_name = renpy.input("What is your name?", length=12).strip()

    g "Hello, [player_name]."

    pause 5.0

    menu:
        "Which way?"

        "Left":
            $ visits += 1
            g "You went left."

        "Right":
            g "You went right."

        "Secret door" if visits > 10:
            g "Nobody gets here."

    g "The end."

    return
