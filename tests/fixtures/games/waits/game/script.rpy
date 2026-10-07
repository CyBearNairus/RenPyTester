# Fixture: a story full of waits. A run must not sit through any of them (spec RUN-004, RUN-016, RUN-018).

define config.name = "Waits Fixture"

label start:
    "Before the waits."
    pause 30.0
    $ renpy.pause(45.0, hard=True)
    scene black
    with Dissolve(20.0)
    with Pause(25.0)
    python:
        # An interaction built by hand, with nothing to press: it waits for a click or for its time to pass.
        ui.pausebehavior(60.0)
        ui.interact(suppress_overlay=True)
    "After the waits."
    return
