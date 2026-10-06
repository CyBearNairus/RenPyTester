# Fixture: the story depends on a random number, so repeatability needs the seed (spec RUN-010).

define config.name = "Random Fixture"

default roll = 0

label start:
    $ roll = renpy.random.randint(1, 1000000)

    if roll % 2:
        "Odd: [roll]."
    else:
        "Even: [roll]."

    if roll % 3 == 0:
        "Divisible by three."

    $ undefined_function(roll)

    return
