# Fixture: a project that asks to be reloaded when its files change, as one being worked on does (spec RUN-023).
# Original content written for RenPyTester's tests.

define config.name = "Reloads Fixture"

define g = Character("Guide")

init python:
    renpy.set_autoreload(True)

label start:
    g "This game would start again if one of its files changed."
    if renpy.get_autoreload():
        $ raise Exception("The game still reloads itself when its files change.")
    g "The end."
    return
