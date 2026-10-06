# Fixture: a translation that uses a variable the game does not have (spec TL-004).

define config.name = "Translated Variable Fixture"

define g = Character("Guide")

default player_name = "Ana"

label start:
    g "Welcome."

    g "It is good to see you, [player_name]."

    return
