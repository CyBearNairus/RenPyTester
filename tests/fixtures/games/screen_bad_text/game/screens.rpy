# The menu screens of the fixture. The story never shows them.

screen help():
    tag menu
    vbox:
        text "Help"
        text "Press {b}Enter to go on."
        textbutton "Return" action Return()
