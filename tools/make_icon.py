"""Draws RenPyTester's icon and writes it in the sizes the program uses (spec GUI-013).

The icon is a speech bubble, for a story told in dialogue, with a check mark in it, for a story
that was checked. It is original artwork, drawn here in code so that it can be changed and made
again; the files it writes are committed, and the program needs nothing but them.

    python tools/make_icon.py

Needs Pillow, which is a development tool only: nothing in the program imports it.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "renpytester" / "assets"
# Drawn large and scaled down, so that edges come out smooth at every size.
CANVAS = 1024
PNG_SIZES = (16, 32, 48, 256)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND_TOP = (92, 74, 196)
BACKGROUND_BOTTOM = (44, 34, 110)
BUBBLE = (255, 255, 255)
CHECK = (24, 160, 96)


def background():
    """A rounded square, a little lighter at the top than at the bottom."""
    gradient = Image.new("RGB", (1, CANVAS))
    for y in range(CANVAS):
        share = y / (CANVAS - 1)
        gradient.putpixel((0, y), tuple(
            round(top + (bottom - top) * share) for top, bottom in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM)))
    square = gradient.resize((CANVAS, CANVAS)).convert("RGBA")
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((24, 24, CANVAS - 24, CANVAS - 24), radius=210, fill=255)
    square.putalpha(mask)
    return square


def draw():
    image = background()
    pen = ImageDraw.Draw(image)

    # The speech bubble, with its tail at the lower left.
    pen.rounded_rectangle((150, 190, 874, 700), radius=150, fill=BUBBLE)
    pen.polygon([(270, 640), (250, 860), (470, 690)], fill=BUBBLE)

    # The check mark: two thick strokes with round ends and a round elbow.
    start, elbow, end = (330, 450), (460, 575), (700, 320)
    width = 84
    pen.line([start, elbow, end], fill=CHECK, width=width, joint="curve")
    for x, y in (start, elbow, end):
        pen.ellipse((x - width // 2, y - width // 2, x + width // 2, y + width // 2), fill=CHECK)
    return image


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    image = draw()
    for size in PNG_SIZES:
        image.resize((size, size), Image.LANCZOS).save(ASSETS / ("icon-%d.png" % size), optimize=True)
    image.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.ico", sizes=[(size, size) for size in ICO_SIZES])
    print("wrote %d files to %s" % (len(PNG_SIZES) + 1, ASSETS))


if __name__ == "__main__":
    main()
