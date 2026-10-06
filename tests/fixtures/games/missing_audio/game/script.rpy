# Fixture: music and a sound whose files are not there (spec ERR-003).

define config.name = "Missing Audio Fixture"

label start:
    "Quiet."

    play music "audio/theme_that_was_renamed.ogg"

    "Still quiet."

    play sound "<from 0.5>audio/click_that_was_deleted.ogg"

    "The end."

    return
