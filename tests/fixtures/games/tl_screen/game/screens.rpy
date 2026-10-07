# The menu screens of the fixture. The story never shows them.

screen about():
    tag menu
    vbox:
        text _("Made by [studio].")
        textbutton _("Return") action Return()
