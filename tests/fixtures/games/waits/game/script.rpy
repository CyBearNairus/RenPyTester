# Fixture: a story full of waits. A run must not sit through any of them (spec RUN-004, RUN-016).

define config.name = "Waits Fixture"

label start:
    "Before the waits."
    pause 30.0
    $ renpy.pause(45.0, hard=True)
    scene black
    with Dissolve(20.0)
    with Pause(25.0)
    "After the waits."
    return
