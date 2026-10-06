# Fixture: one language is complete, the other lacks a line of dialogue and a menu choice (spec TL-001, TL-005).

define config.name = "Untranslated Fixture"

define g = Character("Guide")

label start:
    g "The first line has a translation."

    g "The second line was added later."

    menu:
        "An old choice":
            g "You took the old choice."

        "A new choice":
            g "You took the new choice."

    return
