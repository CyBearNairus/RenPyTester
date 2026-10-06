# Fixture: problems that only the engine's lint finds, because the story never reaches them (spec 4.6).

define config.name = "Lint Fixture"

define g = Character("Guide")

image known = Solid("#336699")

label start:
    show known

    g "This path is fine."

    return

label never_reached:
    show unknown_picture

    g "This line has a {b}tag that is never closed."

    g "This line uses {nosuchtag}a tag that does not exist{/nosuchtag}."

    play music "audio/missing_song.ogg"

    jump label_that_does_not_exist

label also_never_reached:
    nobody "This speaker was never defined."

    return
