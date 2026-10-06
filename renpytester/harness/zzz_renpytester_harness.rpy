# RenPyTester harness.
#
# This file is copied into a game's game/ folder for the duration of a test run and removed
# afterwards. If you find it in your game and no test is running, it is safe to delete.
# It does nothing unless the RENPYTESTER_EVENTS environment variable is set.
#
# It runs on the Python embedded in the game's engine, which can be as old as 3.9, and may only use
# the standard library and the Ren'Py API (spec ARCH-001).

init 999 python hide:

    def _renpytester_install():
        import json
        import os
        import random
        import sys
        import time
        import traceback

        import renpy.display.core as core
        import renpy.error as engine_error
        import renpy.execution as execution

        PROTOCOL = 1
        HARNESS_MARK = "zzz_renpytester_"

        settings = json.loads(os.environ.get("RENPYTESTER_SETTINGS") or "{}")
        seed = int(settings.get("seed", 0))
        input_value = settings.get("input_value", "Tester")
        max_steps = int(settings.get("max_steps", 200000))
        heartbeat_seconds = float(settings.get("heartbeat_seconds", 1.0))

        events = open(os.environ["RENPYTESTER_EVENTS"], "a", encoding="utf-8")

        def emit(ev, **fields):
            fields["ev"] = ev
            events.write(json.dumps(fields, default=str) + "\n")
            events.flush()

        state = {
            "starts": 0,
            "steps": 0,
            "interactions": 0,
            "executed": set(),
            "path": [],
            "taken": {},
            "label": None,
            "interact_type": None,
            "last_beat": time.time(),
            "finished": False,
        }

        # ------------------------------------------------------------------------------- helpers

        def is_game_file(filename):
            filename = filename.replace("\\", "/")
            return not (filename.startswith("renpy/") or filename.startswith("common/") or HARNESS_MARK in filename)

        def location(name):
            try:
                node = renpy.game.script.lookup(name)
                return node.filename.replace("\\", "/"), node.linenumber
            except Exception:
                return None, None

        def here():
            return location(renpy.game.context().current)

        def story_statements():
            """Statements a playthrough could execute (spec EXP-005), as a name -> node mapping."""
            skip = set()

            def mark(node):
                skip.add(node.name)

            for _priority, node in renpy.game.script.initcode:
                if hasattr(node, "get_children"):
                    node.get_children(mark)

            not_story = (
                "Testcase", "EndTranslate", "TranslateString", "TranslatePython", "TranslateBlock",
                "TranslateEarlyBlock", "Init", "EarlyPython")

            found = {}
            for node in renpy.game.script.all_stmts:
                if node.name in skip or not is_game_file(node.filename):
                    continue
                if type(node).__name__ in not_story or getattr(node, "language", None) is not None:
                    continue
                if node.filename.replace("\\", "/").startswith("game/tl/"):
                    continue
                found[node.name] = node

            # The parser adds a return at the end of every file; no playthrough reaches most of them.
            last = {}
            for node in found.values():
                if node.filename not in last or node.linenumber >= last[node.filename].linenumber:
                    last[node.filename] = node
            for node in last.values():
                if type(node).__name__ == "Return":
                    del found[node.name]

            return found

        def game_info():
            return {
                "protocol": PROTOCOL,
                "renpy": list(renpy.version_tuple)[:3],
                "renpy_version": renpy.version_only,
                "python": sys.version.split()[0],
                "name": config.name,
                "version": config.version,
                "languages": sorted(i for i in renpy.known_languages() if i),
            }

        def coverage():
            story = story_statements()
            per_file = {}
            for name, node in story.items():
                entry = per_file.setdefault(node.filename.replace("\\", "/"), [0, 0])
                entry[1] += 1
                if name in state["executed"]:
                    entry[0] += 1
            executed = sum(i[0] for i in per_file.values())
            return {"executed": executed, "total": len(story), "files": per_file}

        def finding(cls, severity, message_id, params, filename=None, line=None, trace=None):
            if filename is None:
                filename, line = here()
            emit(
                "finding", cls=cls, severity=severity, message_id=message_id, params=params, file=filename,
                line=line, label=state["label"], path=list(state["path"]), traceback=trace)

        def finish(reason):
            """Ends the run. Never returns."""
            if not state["finished"]:
                state["finished"] = True
                emit("path_end", reason=reason, path=list(state["path"]))
                emit("done", steps=state["steps"], interactions=state["interactions"], coverage=coverage())
            original_quit()

        def decide(kind, options, unavailable=()):
            """Records a decision and returns the index of the option to take.

            The first option is taken (EXP-006). When the same decision point comes round again on
            the same path, the next untried option is taken instead, so that hub menus are walked
            through instead of looped; when every option has been tried, the path ends.
            """
            filename, line = here()
            taken = state["taken"].setdefault(renpy.game.context().current, set())
            untried = [i for i in range(len(options)) if i not in taken]
            if not untried:
                finish("exhausted")
            pick = untried[0]
            taken.add(pick)
            entry = {
                "kind": kind, "file": filename, "line": line, "choice": options[pick] if options else None,
                "index": pick}
            state["path"].append(entry)
            emit("decision", options=list(options), unavailable=list(unavailable), steps=state["steps"], **entry)
            return pick

        # ----------------------------------------------------------- statements (RUN-008, RUN-009)

        def per_statement():
            # Replaces the engine's infinite-loop check, which is called once per executed statement.
            name = renpy.game.context().current
            state["executed"].add(name)
            state["steps"] += 1

            node = renpy.game.script.namemap.get(name)
            if type(node).__name__ == "Label" and isinstance(name, str) and not name.startswith("_"):
                state["label"] = name

            if state["steps"] % 64 == 0:
                now = time.time()
                if now - state["last_beat"] >= heartbeat_seconds:
                    state["last_beat"] = now
                    filename, line = location(name)
                    emit("heartbeat", file=filename, line=line, steps=state["steps"])

            if state["steps"] > max_steps:
                finding("loop", "warning", "finding.loop", {"steps": max_steps})
                finish("loop")

        execution.check_infinite_loop = per_statement

        # ------------------------------------------------------ interactions (RUN-002, -004, -006)

        original_ui_interact = renpy.ui.interact

        def ui_interact(type="misc", roll_forward=None, **kwargs):
            # Transitions call the interface directly, so the type is only trustworthy while a
            # ui.interact call is on the stack.
            previous = state["interact_type"]
            state["interact_type"] = type
            try:
                return original_ui_interact(type=type, roll_forward=roll_forward, **kwargs)
            finally:
                state["interact_type"] = previous

        renpy.ui.interact = ui_interact

        def screen_buttons(ctx):
            found = []

            def visit(d):
                if isinstance(d, renpy.display.behavior.Button) and getattr(d, "action", None) is not None:
                    words = []

                    def collect(child):
                        if isinstance(child, renpy.text.text.Text):
                            words.append("".join(i for i in child.text if isinstance(i, str)))

                    d.visit_all(collect)
                    action = d.action[0] if isinstance(d.action, (list, tuple)) and d.action else d.action
                    # No memory addresses in labels: paths must read the same on every run (NFR-001).
                    found.append((" ".join(words).strip() or "(%s)" % type(action).__name__, d))

            scene_lists = ctx.scene_lists
            for layer in scene_lists.layers:
                for entry in scene_lists.layers[layer]:
                    d = entry.displayable
                    if isinstance(d, renpy.display.screen.ScreenDisplayable):
                        d.update()
                    d.visit_all(visit)

            return [(label, d) for label, d in found if renpy.is_sensitive(d.action)]

        def interact_with_screen(ctx):
            for _attempt in range(50):
                buttons = screen_buttons(ctx)
                if not buttons:
                    finding("stuck", "warning", "finding.stuck", {})
                    finish("stuck")
                pick = decide("screen", [label for label, d in buttons])
                value = renpy.run(buttons[pick][1].action)
                if value is not None:
                    return value
            finding("stuck", "warning", "finding.stuck", {})
            finish("stuck")

        passive = (None, "say", "pause", "with", "nvl", "movie")

        def interact(self, clear=True, suppress_window=False, trans_pause=False, **kwargs):
            state["interactions"] += 1
            ctx = renpy.game.context()
            kind = state["interact_type"]

            if kind in passive or trans_pause:
                value = True
            elif kind == "input":
                value = input_value
            elif kind not in ("screen", "imagemap") and not screen_buttons(ctx):
                # A hand-built interaction with nothing to click, such as a movie cutscene, waits for a
                # click or a timeout. Either way the game carries on.
                value = True
            else:
                value = interact_with_screen(ctx)

            # What the engine does when an interaction ends.
            if clear:
                ctx.scene_lists.replace_transient()
            self.end_transitions()
            self.restart_interaction = True
            ctx.mark_seen()
            ctx.scene_lists.shown_window = False
            if renpy.game.log is not None:
                renpy.game.log.did_interaction = True

            return value

        core.Interface.interact = interact

        # -------------------------------------------------------------- menus (RUN-003, EXP-006)

        def unavailable_choices():
            node = renpy.game.script.namemap.get(renpy.game.context().current)
            rv = []
            for item in getattr(node, "items", None) or []:
                try:
                    label, condition, block = item[0], item[1], item[2]
                    if block is not None and not renpy.python.py_eval(condition):
                        rv.append(label)
                except Exception:
                    pass
            return rv

        def menu(items, *args, **kwargs):
            choices = [(label, value) for label, value in items if value is not None]
            if not choices:
                return None
            pick = decide("menu", [label for label, value in choices], unavailable_choices())
            value = choices[pick][1]
            if isinstance(value, renpy.ui.ChoiceReturn):
                value = value.value
            return value

        store.menu = menu

        # ----------------------------------------------------------------------- input (RUN-005)

        def text_input(prompt, default="", allow=None, exclude="{}", length=None, **kwargs):
            value = input_value
            if allow:
                value = "".join(i for i in value if i in allow)
            if exclude:
                value = "".join(i for i in value if i not in exclude)
            if length is not None:
                value = value[:length]
            if not value:
                value = default
            filename, line = here()
            entry = {"kind": "input", "file": filename, "line": line, "choice": value, "index": 0}
            state["path"].append(entry)
            emit("decision", options=[value], unavailable=[], steps=state["steps"], **entry)
            return value

        renpy.input = text_input

        # ------------------------------------------------------------ exceptions (ERR-002, NFR-004)

        original_report_exception = engine_error.report_exception

        def report_exception(error, *args, **kwargs):
            # Every engine version calls this first when a statement raises, while the exception is
            # still being handled. Later steps differ between versions, so this is the one place to hook.
            if state["starts"] == 0 or state["finished"]:
                return original_report_exception(error, *args, **kwargs)

            trace = traceback.format_exc()
            frames = traceback.extract_tb(sys.exc_info()[2])

            if frames and HARNESS_MARK in frames[-1].filename.replace("\\", "/"):
                emit("harness_error", message="%s: %s" % (type(error).__name__, error), traceback=trace)
                finish("harness error")

            finding(
                "exception", "error", "finding.exception", {"type": type(error).__name__, "message": str(error)},
                trace=trace)
            finish("exception")

        engine_error.report_exception = report_exception

        # ------------------------------------------------------- start and end of a path (RUN-007)

        original_quit = renpy.quit

        def quit(*args, **kwargs):
            if not state["finished"]:
                state["finished"] = True
                emit("path_end", reason="quit", path=list(state["path"]))
                emit("done", steps=state["steps"], interactions=state["interactions"], coverage=coverage())
            return original_quit(*args, **kwargs)

        renpy.quit = quit

        def started():
            state["starts"] += 1
            if state["starts"] > 1:
                # The engine is starting the game again: the story returned to the main menu.
                finish("end")
            renpy.random.seed(seed)
            random.seed(seed)
            emit("start", seed=seed)

        config.start_callbacks.append(started)

        # ------------------------------------------------------------------- commands (GAME-006)

        def info_command():
            emit("hello", **game_info())
            emit("done", steps=0, interactions=0, coverage=None)
            return False

        renpy.arguments.register_command("renpytester_info", info_command)

        if renpy.game.args.command == "run":
            emit("hello", **game_info())

    import os as _renpytester_os

    if _renpytester_os.environ.get("RENPYTESTER_EVENTS"):
        _renpytester_install()
