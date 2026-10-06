# Fixture: a game whose own script creates, changes and deletes files in its folder (spec SAFE-006, SAFE-007).

define config.name = "Writing Fixture"

define g = Character("Guide")

label start:
    python:
        import os

        data = os.path.join(config.gamedir, "data")
        with open(os.path.join(data, "visit_log.txt"), "w") as visit_log:
            visit_log.write("visited\n")
        with open(os.path.join(data, "counter.txt"), "a") as counter:
            counter.write("one more visit\n")
        if os.path.exists(os.path.join(data, "old_notes.txt")):
            os.remove(os.path.join(data, "old_notes.txt"))

    g "The game has written to its own folder."

    return
