# Fixture: a picture is shown that was never defined (spec ERR-004).

define config.name = "Undefined Image Fixture"

image known = Solid("#336699")

label start:
    show known

    "A picture that exists."

    show stranger smiling

    "A picture that does not."

    return
