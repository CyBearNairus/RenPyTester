# Fixture: a game that rewrites one of its own script files as it starts (spec RUN-027).
#
# Each start takes the next number, by making a file named after it. Odd starts empty z_chapter.rpy
# and take three seconds to fill it again. Even starts leave it alone, but read it only a second and
# a half after starting. An even start that comes while an odd one is still at work therefore reads
# an empty file, and the label in it goes missing. Starts that follow one another always read a
# whole file.

python early hide:
    import os
    import shutil
    import time

    def take_a_number():
        number = 0
        while True:
            name = os.path.join(renpy.config.gamedir, "start-%d.txt" % number)
            try:
                os.close(os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return number
            except OSError:
                number += 1

    template = os.path.join(renpy.config.gamedir, "chapter_template.txt")
    chapter = os.path.join(renpy.config.gamedir, "z_chapter.rpy")

    if take_a_number() % 2:
        open(chapter, "w").close()
        time.sleep(3.0)
        shutil.copyfile(template, chapter)
    else:
        time.sleep(1.5)
