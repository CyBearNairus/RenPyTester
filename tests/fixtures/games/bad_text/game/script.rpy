# Fixture: text tags that are unknown or never closed, in dialogue and in a menu (spec ERR-005).

define config.name = "Bad Text Fixture"

define g = Character("Guide")

label start:
    g "This line is {b}fine{/b}."

    g "This tag is {wobble}not a real one{/wobble}."

    g "This tag is {i}never closed."

    menu:
        "Pick {b}one."

        "First {colour=#f00}choice{/colour}":
            "Done."

    return
