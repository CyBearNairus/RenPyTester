# Fixture: a house that is walked around day after day, where what a room holds depends on the day, and the
# kitchen crashes on the third (spec EXP-021).
# Original content written for RenPyTester's tests.

define config.name = "Hub Days Fixture"

default day = 1

label start:
    "You move in."

label house:
    menu:
        "Kitchen":
            jump kitchen

        "Bedroom":
            jump bedroom

label kitchen:
    if day == 1:
        "Breakfast."
    elif day == 2:
        "Lunch."
    else:
        $ burn_the_dinner()
    jump house

label bedroom:
    "You sleep."
    $ day += 1
    jump house
