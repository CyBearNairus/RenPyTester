# Fixture: the game asks for something only a real screen can give (spec ERR-012).

define config.name = "Needs Display Fixture"

label start:
    "Copying to the clipboard."

    python:
        import pygame.scrap
        pygame.scrap.put(pygame.scrap.SCRAP_TEXT, b"hello")

    return
