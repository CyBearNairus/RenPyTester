# Fixture: a story that goes round forever (spec RUN-009).

define config.name = "Loop Fixture"

label start:
    "Round and round."

    jump start
