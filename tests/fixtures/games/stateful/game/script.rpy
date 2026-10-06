# Fixture: each branch changes a variable; a snapshot that leaked state would reach the last branch
# (spec EXP-002).

define config.name = "Stateful Fixture"

default points = 0
default visited = []

label start:
    $ points = 1
    $ visited.append("start")

    menu:
        "Add":
            $ points += 10
            $ visited.append("add")

        "Double":
            $ points *= 2
            $ visited.append("double")

    if points == 11 and visited == ["start", "add"]:
        "Eleven."
    elif points == 2 and visited == ["start", "double"]:
        "Two."
    else:
        $ state_leaked_between_branches()

    return
