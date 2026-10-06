# Fixture: a game that can only be played through with a settings file (spec CFG-005, CFG-006).
# Its renpytester.toml gives the player two tickets, types the right door code, and leaves out the
# arcade and the credits, which fail without the parts of the game this fixture does not have.

define config.name = "Configured Fixture"

define g = Character("Guide")

default tickets = 0

label start:
    menu:
        "Go in" if tickets >= 2:
            jump hall

        "Stay out":
            g "You stay outside."

    return

label hall:
    $ door_code = renpy.input("What is the door code?")
    $ visitor = renpy.input("What is your name?")

    call arcade

    if door_code == "4721":
        g "The vault opens, [visitor]."
        jump vault

    g "Wrong code."

    return

label vault:
    g "It is full of gold."

    jump credits_roll

label arcade:
    $ arcade_score = play_arcade_machine()

    return

label credits_roll:
    $ roll_the_credits()

    return
