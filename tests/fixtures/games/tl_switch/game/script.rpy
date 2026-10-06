# Fixture: switching to the translation fails, because its set-up code uses a name that does not exist (spec TL-002).

define config.name = "Language Switch Fixture"

define g = Character("Guide")

label start:
    g "This game cannot be played in its other language."

    return
