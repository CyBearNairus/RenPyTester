# Fixture: after a minigame, the script copies its result, jumps, and tests it in several ways (spec RUN-024).
# Original content written for RenPyTester's tests.

define config.name = "Minigame Inference Fixture"

define g = Character("Guide")

screen archery():
    # Nothing to press: the player aims with the mouse.
    text "Aim..."

label start:
    g "You have three arrows."
    call screen archery
    $ medal = _return
    jump prize_giving

label prize_giving:
    if medal in ("gold", "silver"):
        g "A medal for you."
    elif medal == "bronze":
        g "So close."
    else:
        g "Better luck next time."
    if arrows_left > 2:
        g "And you have arrows to spare."
    g "The end."
    return
