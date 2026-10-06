# Fixture: an image is defined, but the file it points to is not there (spec ERR-003).

define config.name = "Missing Image File Fixture"

image bg room = "images/room_that_was_deleted.png"

label start:
    "Before the room."

    scene bg room

    "In the room."

    return
