"""Writes a game big enough to measure speed with (spec RUN-013, NFR-005).

A game of 50,000 words is too much to keep as a fixture, and its text does not matter: only its
size and shape do. So it is made when the test runs, the same every time, out of a handful of
words written for this repository. Each chapter is some dialogue, a menu with three answers that
each lead to more dialogue, and a jump to the next chapter.
"""

from pathlib import Path

WORDS = (
    "the lantern keeper walks along a quiet harbour while morning rain taps on old copper roofs and "
    "somebody far away is singing about ships that never came home before winter").split()

LINES_BEFORE_MENU = 30
LINES_PER_ANSWER = 15
LINES_AFTER_MENU = 20
WORDS_PER_LINE = 12
ANSWERS = ("Take the upper road", "Follow the river", "Wait for the ferry")


def write_big_game(folder, words=50000):
    """Writes the game into `folder` and returns (words of dialogue, lines of dialogue, chapters)."""
    position = 0

    def line(speaker):
        nonlocal position
        text = " ".join(WORDS[(position + index * 7) % len(WORDS)] for index in range(WORDS_PER_LINE))
        position += 1
        return '%s "%s."' % (speaker, text.capitalize())

    per_chapter = (LINES_BEFORE_MENU + len(ANSWERS) * LINES_PER_ANSWER + LINES_AFTER_MENU) * WORDS_PER_LINE
    chapters = -(-words // per_chapter)
    script = [
        "# A game made by tests/e2e/big_game.py to measure speed with. It is not a fixture and is never kept.",
        "", 'define config.name = "Big Game"', "", 'define k = Character("Keeper")',
        'define s = Character("Stranger")', "", "default kindness = 0", "", "label start:",
        "    jump chapter_1", ""]
    lines = 0
    for chapter in range(1, chapters + 1):
        script.append("label chapter_%d:" % chapter)
        script.extend("    " + line("k" if index % 2 else "s") for index in range(LINES_BEFORE_MENU))
        script.append("    menu:")
        for number, answer in enumerate(ANSWERS):
            script.append('        "%s":' % answer)
            script.append("            $ kindness += %d" % number)
            script.extend("            " + line("k") for _index in range(LINES_PER_ANSWER))
        script.extend("    " + line("s") for _index in range(LINES_AFTER_MENU))
        script.append("    jump chapter_%d" % (chapter + 1) if chapter < chapters else "    return")
        script.append("")
        lines += LINES_BEFORE_MENU + len(ANSWERS) * LINES_PER_ANSWER + LINES_AFTER_MENU

    game = Path(folder) / "game"
    game.mkdir(parents=True, exist_ok=True)
    (game / "script.rpy").write_text("\n".join(script), encoding="utf-8")
    return lines * WORDS_PER_LINE, lines, chapters
