"""An editor that opens nothing.

When a game fails, Ren'Py opens traceback.txt or errors.txt in the system's text editor (Notepad on
Windows). During a test run that would put windows on the user's screen, so the engine is pointed
at this file through the RENPY_EDIT_PY environment variable instead (spec GAME-010).

The engine executes this file with its own Python and expects it to define a class named Editor.
"""


class Editor(object):
    has_projects = False

    def begin(self, new_window=False, **kwargs):
        pass

    def end(self, **kwargs):
        pass

    def open(self, filename, line=None, **kwargs):
        pass

    def open_project(self, directory):
        pass
