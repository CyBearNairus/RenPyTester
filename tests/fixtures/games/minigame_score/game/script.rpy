# Fixture: a minigame whose result the script reads from a variable the game already has, so nothing can
# be inferred and each place the script may go is tried (spec RUN-020).

define config.name = "Minigame Score Fixture"

default score = 0

screen arena():
    text "Fight!"

label start:
    "The arena."

    call screen arena

    if score >= 3:
        jump victory
    else:
        jump defeat

label victory:
    "You won."

    return

label defeat:
    "You lost."

    return
