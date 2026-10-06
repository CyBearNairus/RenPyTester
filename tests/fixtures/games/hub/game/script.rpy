# Fixture: a menu the story keeps coming back to until the player leaves (spec EXP-006).

define config.name = "Hub Fixture"

label start:
    "Welcome."

label hub:
    menu:
        "Ask about the weather":
            "It is raining."
            jump hub

        "Ask about the town":
            "It is small."
            jump hub

        "Ask about the road":
            "It is long."
            jump hub

        "Leave":
            "Goodbye."

    return
