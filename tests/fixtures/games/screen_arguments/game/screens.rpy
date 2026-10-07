# The menu screens of the fixture. The story never shows them.

# The engine shows this one with a question and what its two answers do.
screen confirm(message, yes_action, no_action):
    modal True
    vbox:
        text "[message]"
        textbutton "Yes" action yes_action
        textbutton "No" action no_action

# Nobody but this game knows what to show this one with.
screen save(shelf):
    tag menu
    vbox:
        text "Shelf [shelf]"
        textbutton "Return" action Return()
