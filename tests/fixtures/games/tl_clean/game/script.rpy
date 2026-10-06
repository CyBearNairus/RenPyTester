# Fixture: a game with a complete translation that has nothing wrong with it (spec 4.7).

define config.name = "Translated Fixture"

define g = Character(_("Guide"))

default player_name = "Ana"

label start:
    g "Welcome, [player_name]."

    menu:
        "Stay":
            g "You stay {b}here{/b}."

        "Leave":
            g "You leave."

    return
