# Fixture: one mistake that both lint and a playthrough find, to check it is reported once (spec LINT-002).

define config.name = "Missing Label Fixture"

label start:
    "Before the bug."

    jump chapter_that_was_renamed
