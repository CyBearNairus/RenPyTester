# Fixture: a minigame the tool cannot play, followed by a branch on how it ended (spec RUN-017, RUN-019).

define config.name = "Minigame Fixture"

screen puzzle():
    text "Solve the puzzle with the mouse."

label start:
    "A puzzle blocks the way."

    call screen puzzle

    $ outcome = _return

    if outcome == "solved":
        "The door opens."
    elif outcome == "failed":
        $ undefined_after_failure()
    else:
        "You walk away."

    "The end."

    return
