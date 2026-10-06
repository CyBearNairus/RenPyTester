# Fixture: labels that playing from the start never reaches, or reaches in a different state
# (spec EXP-007, EXP-012, EXP-019, EXP-020).

define config.name = "Labels Fixture"

label start:
    $ points = 0
    "A short story."
    call add_points(2)
    jump chapter

label chapter:
    # Fails when started here by itself, because nothing has set the points. Playing from the start
    # runs it without trouble, so that is not reported.
    $ points += 1
    "Points: [points]."
    if points > 100:
        jump secret
    jump broken

label add_points(amount):
    # Needs an argument, so it cannot be started by itself.
    $ points += amount
    return

label secret:
    "Nobody gets here by playing."

    menu:
        "Open the box":
            $ open_the_box()

        "Leave it":
            "You leave."

    jump ending

label broken:
    # Fails however it is reached.
    $ this_is_missing()
    return

label ending:
    "The end."
    return
