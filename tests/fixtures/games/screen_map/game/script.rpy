# Fixture: a map whose places are hotspots that jump, each written as "clicked" with a list of actions, and
# one of the places crashes (spec RUN-006).
# Original content written for RenPyTester's tests.

define config.name = "Screen Map Fixture"

define g = Character("Guide")

default moves = 0

screen house():
    imagemap:
        ground Solid("#222222")
        hover Solid("#444444")
        hotspot (0, 0, 100, 100) clicked [SetVariable("moves", moves + 1), Jump("garden")]
        hotspot (100, 0, 100, 100) clicked [SetVariable("moves", moves + 1), Jump("cellar")]

screen stairs():
    textbutton "Go back up" action Return()

label start:
    g "Where to?"
    call screen house

label garden:
    call screen stairs
    g "A quiet garden."
    g "The end."
    return

label cellar:
    $ fall_down_the_stairs()
