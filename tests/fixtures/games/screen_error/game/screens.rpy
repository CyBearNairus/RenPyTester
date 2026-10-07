# The menu screens of the fixture. The story never shows them.

screen about():
    tag menu
    vbox:
        text "Screen Error Fixture"
        textbutton "Return" action Return()

screen preferences():
    tag menu
    vbox:
        text "Preferences"
        textbutton "Louder" action SetVariable("volume", volume_level + 1)
        textbutton "Return" action Return()
