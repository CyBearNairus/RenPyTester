# RenPyTester harness.
#
# This file is copied into a game's game/ folder for the duration of a test run and removed
# afterwards. If you find it in your game and no test is running, it is safe to delete.
# It does nothing unless the RENPYTESTER_EVENTS environment variable is set.
#
# It runs on the Python embedded in the game's engine, which can be as old as 3.9, and may only use
# the standard library and the Ren'Py API (spec ARCH-001).
#
# How a run works (spec ARCH-007, ARCH-008):
#   * The engine's interaction layer is replaced, so nothing is drawn and nothing waits.
#   * Every menu, screen with buttons and text prompt is a "decision". The first option is taken, and
#     a snapshot of the game is kept for each other option, so that it can be explored later without
#     replaying the game from the start.
#   * When a path ends (the story ends, crashes, or gets stuck), the most recent snapshot is restored
#     and its option is taken. The run ends when no snapshots are left.

init 999 python hide:

    def _renpytester_install():
        import io
        import json
        import os
        import random
        import sys
        import time
        import traceback
        import zlib

        import renpy.display.core as core
        import renpy.error as engine_error
        import renpy.execution as execution

        PROTOCOL = 2
        HARNESS_MARK = "zzz_renpytester_"

        # Settings arrive in a file: a list of branches to resume can be too long for an environment variable.
        settings = {}
        if os.environ.get("RENPYTESTER_SETTINGS"):
            with open(os.environ["RENPYTESTER_SETTINGS"], "r", encoding="utf-8") as settings_file:
                settings = json.load(settings_file)
        seed = int(settings.get("seed", 0))
        input_value = settings.get("input_value", "Tester")
        explore = settings.get("strategy", "explore") == "explore"
        max_steps = int(settings.get("max_steps", 200000))
        max_paths = int(settings.get("max_paths", 5000))
        max_time = float(settings.get("max_time", 600))
        max_depth = int(settings.get("max_depth", 500))
        heartbeat_seconds = float(settings.get("heartbeat_seconds", 1.0))

        events = open(os.environ["RENPYTESTER_EVENTS"], "a", encoding="utf-8")

        def emit(ev, **fields):
            fields["ev"] = ev
            events.write(json.dumps(fields, default=str) + "\n")
            events.flush()

        state = {
            "starts": 0,
            "steps": 0,
            "path_steps": 0,
            "interactions": 0,
            "paths": 0,
            # Statements executed, and those not yet reported to the orchestrator.
            "executed": set(),
            "unreported": [],
            # The current path: its decisions, and which options it has already taken where.
            "path": [],
            "taken": {},
            "label": None,
            "interact_type": None,
            # Exploration.
            "scheduled": set(),
            "stack": [],
            "forced": None,
            "replay": None,
            "resume": [list(i) for i in settings.get("resume") or []],
            "root": None,
            "need_root": False,
            "limit": None,
            "started_at": time.time(),
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

        def node_id(node):
            # Stable between processes running the same compiled script, so coverage can be merged.
            name = node.name
            if isinstance(name, str):
                return "label:" + name
            return "%s#%s" % (node.filename.replace("\\", "/"), name[-1])

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
            # It is the last statement the file was given a number for.
            def serial(node):
                number = node.name[-1] if isinstance(node.name, tuple) else None
                return number if isinstance(number, int) else -1

            last = {}
            for node in found.values():
                if node.filename not in last or serial(node) > serial(last[node.filename]):
                    last[node.filename] = node
            for node in last.values():
                if type(node).__name__ == "Return":
                    del found[node.name]

            return found

        story = story_statements()

        def is_public_label(node):
            return type(node).__name__ == "Label" and isinstance(node.name, str) and not node.name.startswith("_")

        def script_map():
            """Every story statement, by file and by the label it sits under, for the coverage report."""
            files = {}
            for node in story.values():
                files.setdefault(node.filename.replace("\\", "/"), []).append(node)

            labels = {}
            for filename, nodes in files.items():
                nodes.sort(key=lambda n: (n.linenumber, str(n.name)))
                current = None
                for node in nodes:
                    if is_public_label(node):
                        current = labels.setdefault(node.name, {"file": filename, "line": node.linenumber, "ids": []})
                    if current is not None:
                        current["ids"].append(node_id(node))

            return {"files": dict((f, [node_id(n) for n in nodes]) for f, nodes in files.items()), "labels": labels}

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

        def take_unreported():
            rv, state["unreported"] = state["unreported"], []
            return rv

        def indices():
            return [i["index"] for i in state["path"]]

        def waiting():
            return len(state["stack"]) + len(state["resume"])

        def finding(cls, severity, message_id, params, filename=None, line=None, trace=None):
            if filename is None:
                filename, line = here()
            emit(
                "finding", cls=cls, severity=severity, message_id=message_id, params=params, file=filename,
                line=line, label=state["label"], path=list(state["path"]), traceback=trace)

        # ---------------------------------------------------------- snapshots (EXP-002, RUN-010)

        def snapshot():
            roots = renpy.game.log.freeze(None)
            buffer = io.BytesIO()
            renpy.loadsave.dump((roots, renpy.game.log), buffer)
            return zlib.compress(buffer.getvalue(), 1)

        def restore(data):
            """Puts the game back as it was when `data` was taken. Never returns."""
            state["interact_type"] = None
            state["path_steps"] = 0
            roots, log = renpy.loadsave.loads(zlib.decompress(data))
            log.unfreeze(roots, label="_after_load")

        # ------------------------------------------------------------ paths (EXP-001, EXP-003)

        def finish():
            """Ends the run. Never returns."""
            if not state["finished"]:
                state["finished"] = True
                emit(
                    "done", steps=state["steps"], interactions=state["interactions"], paths=state["paths"],
                    covered=take_unreported(), limit=state["limit"])
            original_quit()

        def out_of_budget():
            if state["paths"] >= max_paths:
                return "max_paths"
            if time.time() - state["started_at"] > max_time:
                return "max_time"
            return None

        def start_prefix(prefix):
            state["path"] = []
            state["taken"] = {}
            state["label"] = None
            state["replay"] = list(prefix)
            emit("branch_start", prefix=list(prefix), path=[])

        def next_path(reason):
            """Ends the current path and starts the next one waiting. Never returns."""
            state["paths"] += 1
            state["forced"] = None
            state["replay"] = None
            emit("path_end", reason=reason, path=list(state["path"]), covered=take_unreported())

            limit = out_of_budget()
            if limit and waiting():
                state["limit"] = {"kind": limit, "unexplored": waiting()}
                finish()

            if state["stack"]:
                entry = state["stack"].pop()
                state["path"] = entry["path"]
                state["taken"] = entry["taken"]
                state["label"] = entry["label"]
                state["forced"] = entry["index"]
                random.setstate(entry["random"])
                emit("branch_start", prefix=indices() + [entry["index"]], path=list(state["path"]))
                restore(entry["snapshot"])

            if state["resume"] and state["root"] is not None:
                start_prefix(state["resume"].pop(0))
                random.setstate(state["root"]["random"])
                restore(state["root"]["snapshot"])

            finish()

        def choose(kind, options, unavailable=()):
            """Records a decision and returns the index of the option to take.

            The first option not yet tried anywhere is taken (EXP-001), and each other untried option
            is kept for later with a snapshot. When the same decision point comes round again on one
            path, an option that path has not taken is used, so that hub menus are walked through
            instead of looped; when the path has taken them all, it ends.
            """
            decision = renpy.game.context().current
            taken = state["taken"].setdefault(decision, set())

            # Two options with the same text are told apart by their order.
            keys, seen = [], {}
            for label in options:
                seen[label] = seen.get(label, 0) + 1
                keys.append((decision, label, seen[label]))

            if state["replay"]:
                pick = state["replay"].pop(0)
                if pick >= len(options):
                    next_path("replay mismatch")
            elif state["forced"] is not None:
                pick, state["forced"] = state["forced"], None
                if pick >= len(options):
                    next_path("replay mismatch")
            else:
                untried_here = [i for i in range(len(options)) if i not in taken]
                if not untried_here:
                    next_path("exhausted")
                fresh = [i for i in untried_here if keys[i] not in state["scheduled"]]
                if fresh:
                    pick = fresh[0]
                elif taken:
                    # Back at a hub whose every option is already tried or waiting in a snapshot. Walking
                    # through them again here would repeat that work, so leave: the way out of a hub is
                    # usually listed last.
                    pick = untried_here[-1]
                else:
                    pick = untried_here[0]
                later = [i for i in fresh if i != pick]

                if later and explore and len(state["path"]) < max_depth:
                    data = snapshot()
                    for i in reversed(later):
                        state["scheduled"].add(keys[i])
                        state["stack"].append({
                            "snapshot": data, "index": i, "path": list(state["path"]),
                            "taken": dict((k, set(v)) for k, v in state["taken"].items()),
                            "label": state["label"], "random": random.getstate()})
                        emit("branch", prefix=indices() + [i])

            state["scheduled"].add(keys[pick])
            taken.add(pick)

            filename, line = here()
            entry = {"kind": kind, "file": filename, "line": line, "choice": options[pick], "index": pick}
            state["path"].append(entry)
            emit("decision", options=list(options), unavailable=list(unavailable), steps=state["steps"], **entry)
            return pick

        # ----------------------------------------------------------- statements (RUN-008, RUN-009)

        def per_statement():
            # Replaces the engine's infinite-loop check, which is called once per executed statement.
            name = renpy.game.context().current
            state["steps"] += 1
            state["path_steps"] += 1

            node = story.get(name)
            if node is not None:
                if state["need_root"]:
                    # The first statement of the story: the point every handed-over path starts from.
                    state["need_root"] = False
                    state["root"] = {"snapshot": snapshot(), "random": random.getstate()}
                if name not in state["executed"]:
                    state["executed"].add(name)
                    state["unreported"].append(node_id(node))
                if is_public_label(node):
                    state["label"] = name

            if state["steps"] % 64 == 0:
                now = time.time()
                if now - state["last_beat"] >= heartbeat_seconds:
                    state["last_beat"] = now
                    filename, line = location(name)
                    emit(
                        "heartbeat", file=filename, line=line, steps=state["steps"], paths=state["paths"],
                        waiting=waiting(), covered=take_unreported())
                    if state["starts"] and now - state["started_at"] > max_time:
                        state["limit"] = {"kind": "max_time", "unexplored": waiting()}
                        state["paths"] += 1
                        emit("path_end", reason="max_time", path=list(state["path"]), covered=take_unreported())
                        finish()

            if state["path_steps"] > max_steps:
                finding("loop", "warning", "finding.loop", {"steps": max_steps})
                next_path("loop")

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
                    break
                pick = choose("screen", [label for label, d in buttons])
                value = renpy.run(buttons[pick][1].action)
                if value is not None:
                    return value
            finding("stuck", "warning", "finding.stuck", {})
            next_path("stuck")

        passive = (None, "say", "pause", "with", "nvl", "movie")

        def interact(self, clear=True, suppress_window=False, trans_pause=False, **kwargs):
            state["interactions"] += 1
            ctx = renpy.game.context()
            kind = state["interact_type"]

            if kind in passive or trans_pause:
                value = True
            elif getattr(ctx, "_main_menu", False):
                # The main menu is not part of the story. Leaving it starts the game, which is what a
                # player would do there; its other buttons (load, preferences, quit) are not explored.
                value = True
            elif kind == "input":
                value = input_value
            elif kind not in ("screen", "imagemap") and not screen_buttons(ctx):
                # A hand-built interaction with nothing to click, such as a movie cutscene, waits for a
                # click or a timeout. Either way the game carries on (RUN-018).
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

        # ------------------------------------------------------------------------ menus (RUN-003)

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
            pick = choose("menu", [label for label, value in choices], unavailable_choices())
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
            choose("input", [value])
            return value

        renpy.input = text_input

        # ------------------------------------------------ exceptions (ERR-002, RUN-011, NFR-004)

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
                finish()

            finding(
                "exception", "error", "finding.exception", {"type": type(error).__name__, "message": str(error)},
                trace=trace)
            next_path("exception")

        engine_error.report_exception = report_exception

        # ------------------------------------------------------- start and end of a path (RUN-007)

        original_quit = renpy.quit

        def quit(*args, **kwargs):
            # The game closing itself is a normal ending of this path, not of the run.
            if state["finished"] or state["starts"] == 0:
                return original_quit(*args, **kwargs)
            # Kept in the event log: when a path ends this way unexpectedly, this says what asked for it.
            emit("quit_requested", stack=traceback.format_stack()[-6:-1])
            next_path("quit")

        renpy.quit = quit

        def started():
            state["starts"] += 1
            if state["starts"] > 1:
                # The engine is starting the game again: the story returned to the main menu.
                next_path("end")

            renpy.random.seed(seed)
            random.seed(seed)
            emit("start", seed=seed, map=script_map())

            if state["resume"]:
                # Paths handed over by the orchestrator all begin at the first statement of the story;
                # a snapshot is taken there, so that each can start without restarting the engine.
                state["need_root"] = True
                start_prefix(state["resume"].pop(0))

        config.start_callbacks.append(started)

        # A project in development reloads itself when a script file changes on disk. A reload in the
        # middle of a run restarts the game under the harness's feet, so it is switched off.
        config.autoreload = False

        # ------------------------------------------------------------------- commands (GAME-006)

        def info_command():
            emit("hello", **game_info())
            emit("done", steps=0, interactions=0, paths=0, covered=[], limit=None)
            return False

        renpy.arguments.register_command("renpytester_info", info_command)

        if renpy.game.args.command == "run":
            emit("hello", **game_info())

    import os as _renpytester_os

    if _renpytester_os.environ.get("RENPYTESTER_EVENTS"):
        _renpytester_install()
