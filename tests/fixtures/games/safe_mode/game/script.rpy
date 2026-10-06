# Fixture: the engine is asked for its "safe mode", as happens on Windows whenever the Shift key
# is down while a game starts. It then shows a screen for choosing a renderer instead of the game;
# a run must go straight to the story all the same (spec RUN-025).

define config.name = "Safe Mode Fixture"

init python:
    renpy.game.args.safe_mode = True

label start:
    "The story, not the engine's settings."
    return
