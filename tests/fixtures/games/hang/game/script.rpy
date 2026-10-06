# Fixture: Python that never returns, so the game stops making progress (spec RUN-008).

define config.name = "Hang Fixture"

label start:
    "Before the hang."

    python:
        import time
        while True:
            time.sleep(0.05)

    return
