# Fixture: a screen with two buttons decides where the story goes, and the second way crashes (spec RUN-006).
# Original content written for RenPyTester's tests.

define config.name = "Screen Choice Fixture"

define g = Character("Guide")

screen doors():
    vbox:
        textbutton "Left door" action Return("left")
        textbutton "Right door" action Return("right")

label start:
    g "There are two doors."
    call screen doors
    if _return == "left":
        g "A quiet room."
    else:
        $ fall_into_the_cellar()
    g "The end."
    return
