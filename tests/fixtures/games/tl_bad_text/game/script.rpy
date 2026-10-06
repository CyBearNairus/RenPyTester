# Fixture: text tags that are right in the original and broken in its translation (spec TL-003).

define config.name = "Translated Tags Fixture"

define g = Character("Guide")

label start:
    g "This line is {i}important{/i}."

    menu:
        "Take the {b}red{/b} door":
            g "It was the red one."

    return
