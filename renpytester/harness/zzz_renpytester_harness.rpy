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
#     and its option is taken.
#   * When no snapshots are left, each label is played by itself (spec EXP-007), starting from the
#     state the game had at the first statement of the story. The run ends when no labels are left.

init 999 python hide:

    def _renpytester_install():
        import ast as pyast
        import builtins
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

        PROTOCOL = 3
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
        label_runs = explore and bool(settings.get("labels", True))
        labels_done = set(settings.get("labels_done") or [])
        # Set when this process takes over from one that died after it had finished the story itself.
        story_done = bool(settings.get("story_done"))

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
            # Branches handed over by the orchestrator, each a (label or None, decision indices) pair.
            "resume": [(label, list(prefix)) for label, prefix in settings.get("resume") or []],
            "root": None,
            "need_root": False,
            # Label runs (EXP-007): the labels still to start at, the one being played, the label to
            # jump to once the game is back at the story's first statement, and how deep in calls the
            # label run started.
            "labels": [],
            "labels_only": False,
            "origin": None,
            "goto": None,
            "base_depth": 0,
            "limit": None,
            "started_at": time.time(),
            "last_beat": time.time(),
            "finished": False,
            # True once the path has skipped an interaction it could not play: what follows is a guess.
            "speculative": False,
            "executed_low": set(),
            "unreported_low": [],
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
            # Stable between processes running the same compiled script, so coverage can be merged, and
            # unique within the game: some engine versions name every translation block in a file alike
            # in the last part of the name, so the whole name is used.
            name = node.name
            if isinstance(name, str):
                return "label:" + name
            return "%s#%s" % (node.filename.replace("\\", "/"), "|".join(str(part) for part in name[1:]))

        def story_statements():
            """Statements a playthrough could execute (spec EXP-005), as a name -> node mapping."""
            skip = set()

            def mark(node):
                skip.add(node.name)

            for _priority, node in renpy.game.script.initcode:
                if hasattr(node, "get_children"):
                    node.get_children(mark)

            # "Translate" is the wrapper older engines put around each line of dialogue; the line inside
            # it is the statement, and counting both would make coverage differ between engine versions.
            not_story = (
                "Testcase", "Translate", "EndTranslate", "TranslateString", "TranslatePython", "TranslateBlock",
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

        def take_unreported_low():
            rv, state["unreported_low"] = state["unreported_low"], []
            return rv

        def indices():
            return [i["index"] for i in state["path"] if i["kind"] != "label"]

        def waiting():
            return len(state["stack"]) + len(state["resume"])

        def unexplored():
            return {"unexplored": waiting(), "labels": len(state["labels"])}

        def needs_arguments(node):
            parameters = getattr(node, "parameters", None)
            if parameters is None:
                return False
            try:
                parameters.apply((), {})
                return False
            except Exception:
                return True

        def labels_to_start():
            """Every label a label run starts at, in script order (EXP-020)."""
            nodes = [
                node for node in story.values()
                if is_public_label(node) and node.name != "start" and node.name not in labels_done
                and not needs_arguments(node)]
            nodes.sort(key=lambda n: (n.filename.replace("\\", "/"), n.linenumber, n.name))
            return [node.name for node in nodes]

        def finding(cls, severity, message_id, params, filename=None, line=None, trace=None):
            if filename is None:
                filename, line = here()
            node = story.get(renpy.game.context().current)
            emit(
                "finding", cls=cls, severity=severity, message_id=message_id, params=params, file=filename,
                line=line, label=state["label"], path=list(state["path"]), traceback=trace,
                node=node_id(node) if node is not None else None,
                possible=state["speculative"] and cls != "stuck")

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
                    covered=take_unreported(), covered_low=take_unreported_low(), limit=state["limit"])
            original_quit()

        def out_of_budget():
            if state["paths"] >= max_paths:
                return "max_paths"
            if time.time() - state["started_at"] > max_time:
                return "max_time"
            return None

        def start_at(label):
            """Makes the path about to begin a label run, or, with no label, a path from the game's start."""
            state["origin"] = label
            state["goto"] = label
            state["path"] = []
            state["taken"] = {}
            state["label"] = None
            state["forced"] = None
            state["replay"] = None
            # Whatever a label run meets, it meets in a state no player was necessarily ever in (EXP-013).
            state["speculative"] = label is not None
            if label is not None:
                filename, line = location(label)
                state["path"].append({"kind": "label", "file": filename, "line": line, "choice": label, "index": 0})

        def start_prefix(entry):
            label, prefix = entry
            start_at(label)
            state["replay"] = list(prefix)
            emit("branch_start", prefix=list(prefix), label=label, path=list(state["path"]))

        def to_root():
            random.setstate(state["root"]["random"])
            restore(state["root"]["snapshot"])

        def next_label():
            """Starts the next label run, or ends the run when there is none. Never returns."""
            if not state["labels"]:
                finish()
            label = state["labels"].pop(0)
            start_at(label)
            # Each label run explores by itself, whatever was explored before it (EXP-015).
            state["scheduled"] = set()
            emit("label_start", label=label, path=list(state["path"]))
            to_root()

        def next_path(reason):
            """Ends the current path and starts the next one waiting. Never returns."""
            state["paths"] += 1
            state["forced"] = None
            state["replay"] = None
            emit(
                "path_end", reason=reason, path=list(state["path"]), covered=take_unreported(),
                covered_low=take_unreported_low())

            limit = out_of_budget()
            if limit and (waiting() or state["labels"]):
                state["limit"] = dict(unexplored(), kind=limit)
                finish()

            if state["stack"]:
                entry = state["stack"].pop()
                state["path"] = entry["path"]
                state["taken"] = entry["taken"]
                state["label"] = entry["label"]
                state["speculative"] = entry["speculative"]
                state["origin"] = entry["origin"]
                state["base_depth"] = entry["base_depth"]
                state["goto"] = None
                state["forced"] = entry["index"]
                random.setstate(entry["random"])
                emit(
                    "branch_start", prefix=indices() + [entry["index"]], label=state["origin"],
                    path=list(state["path"]))
                restore(entry["snapshot"])

            if state["root"] is not None:
                if state["resume"]:
                    start_prefix(state["resume"].pop(0))
                    to_root()
                # The story itself is explored first; label runs take what is left (EXP-011).
                next_label()

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
                            "label": state["label"], "random": random.getstate(),
                            "speculative": state["speculative"], "origin": state["origin"],
                            "base_depth": state["base_depth"]})
                        emit("branch", prefix=indices() + [i], label=state["origin"])

            state["scheduled"].add(keys[pick])
            taken.add(pick)

            filename, line = here()
            entry = {"kind": kind, "file": filename, "line": line, "choice": options[pick], "index": pick}
            state["path"].append(entry)
            emit("decision", options=list(options), unavailable=list(unavailable), steps=state["steps"], **entry)
            return pick

        # ----------------------------------------------------------- statements (RUN-008, RUN-009)

        def leaves_label(name):
            origin = state["origin"]
            if name == origin or name.startswith(origin.split(".")[0] + "."):
                return False  # The label itself, or one of its local labels.
            return len(renpy.game.context().return_stack) <= state["base_depth"]

        def per_statement():
            # Replaces the engine's infinite-loop check, which is called once per executed statement.
            name = renpy.game.context().current
            state["steps"] += 1
            state["path_steps"] += 1

            node = story.get(name)
            if node is not None:
                if state["need_root"]:
                    # The first statement of the story: the point every handed-over path and every
                    # label run starts from.
                    state["need_root"] = False
                    state["root"] = {"snapshot": snapshot(), "random": random.getstate(), "name": name}
                    if state["labels_only"]:
                        next_label()
                if state["goto"] is not None and name == state["root"]["name"]:
                    target, state["goto"] = state["goto"], None
                    state["base_depth"] = len(renpy.game.context().return_stack)
                    # Closes the engine's record of this statement, so that a snapshot taken inside the
                    # label goes back into the label, not to here, where nothing says to jump again.
                    renpy.game.log.checkpoint(hard=True)
                    raise renpy.game.JumpException(target)
                if state["origin"] is not None and is_public_label(node) and leaves_label(name):
                    # A label run plays its own label; the one the story moves on to has a run of its own.
                    next_path("label end")
                if state["speculative"]:
                    if name not in state["executed"] and name not in state["executed_low"]:
                        state["executed_low"].add(name)
                        state["unreported_low"].append(node_id(node))
                elif name not in state["executed"]:
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
                        waiting=waiting(), covered=take_unreported(), covered_low=take_unreported_low())
                    if state["starts"] and now - state["started_at"] > max_time:
                        state["limit"] = dict(unexplored(), kind="max_time")
                        state["paths"] += 1
                        emit(
                            "path_end", reason="max_time", path=list(state["path"]), covered=take_unreported(),
                            covered_low=take_unreported_low())
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

        # --------------------------------- getting past minigames (RUN-017, RUN-019 to RUN-021)
        #
        # An interaction with nothing to click, such as a minigame, cannot be played. It is skipped, and
        # the story is continued once for each result the script goes on to check for.

        OTHER = "renpytester-other"

        def known_name(name):
            return hasattr(store, name) or hasattr(builtins, name)

        def add_value(found, name, value):
            values = found.setdefault(name, [])
            if not [v for v in values if type(v) is type(value) and v == value]:
                values.append(value)

        def condition_values(source, tracked, found):
            """Adds to `found` the values that a condition compares each interesting name against."""
            try:
                tree = pyast.parse(str(source).strip(), mode="eval")
            except Exception:
                return

            def interesting(node):
                return isinstance(node, pyast.Name) and (node.id in tracked or not known_name(node.id))

            def constants(node):
                if isinstance(node, pyast.Constant):
                    return [node.value]
                if isinstance(node, (pyast.Tuple, pyast.List, pyast.Set)):
                    return [e.value for e in node.elts if isinstance(e, pyast.Constant)]
                return []

            def truth(node):
                # A name used as a yes-or-no test: both answers are worth trying.
                if isinstance(node, pyast.Name):
                    if interesting(node):
                        add_value(found, node.id, True)
                        add_value(found, node.id, False)
                elif isinstance(node, pyast.UnaryOp) and isinstance(node.op, pyast.Not):
                    truth(node.operand)
                elif isinstance(node, pyast.BoolOp):
                    for value in node.values:
                        truth(value)
                elif isinstance(node, pyast.Attribute):
                    truth(node.value)

            truth(tree.body)

            ordering = (pyast.Lt, pyast.LtE, pyast.Gt, pyast.GtE)
            for node in pyast.walk(tree):
                if not isinstance(node, pyast.Compare):
                    continue
                sides = [node.left] + list(node.comparators)
                values = [v for side in sides for v in constants(side)]
                ordered = [op for op in node.ops if isinstance(op, ordering)]
                for side in sides:
                    if not interesting(side):
                        continue
                    for value in values:
                        add_value(found, side.id, value)
                        if ordered and isinstance(value, (int, float)) and not isinstance(value, bool):
                            add_value(found, side.id, value + 1)
                            add_value(found, side.id, value - 1)

        def look_ahead(node):
            """Reads the script after `node`: what the interaction's result is compared against, and where
            the script may jump. Returns (values for the result, values for other names, labels)."""
            tracked = set(["_return"])
            found = {}
            labels = []
            followed = 0
            node = node.next

            for _step in range(40):
                if node is None:
                    break
                kind = type(node).__name__

                if kind == "If":
                    for condition, block in node.entries:
                        condition_values(condition, tracked, found)
                        for child in block:
                            target = getattr(child, "target", None) or getattr(child, "label", None)
                            if type(child).__name__ in ("Jump", "Call") and not child.expression and target:
                                if target not in labels:
                                    labels.append(target)
                elif kind == "While":
                    condition_values(node.condition, tracked, found)
                elif kind == "Python":
                    # "$ winner = _return": from here on, that name stands for the result too.
                    try:
                        for statement in pyast.parse(node.code.source).body:
                            copied = isinstance(statement, pyast.Assign) and isinstance(statement.value, pyast.Name)
                            if copied and statement.value.id in tracked:
                                for target in statement.targets:
                                    if isinstance(target, pyast.Name):
                                        tracked.add(target.id)
                    except Exception:
                        pass
                elif kind == "Jump" and not node.expression and followed < 3:
                    followed += 1
                    node = renpy.game.script.namemap.get(node.target)
                    continue
                elif kind in ("Return", "Menu"):
                    break

                node = node.next

            results = []
            others = {}
            for name, values in found.items():
                for value in values:
                    if name in tracked:
                        if not [v for v in results if type(v) is type(value) and v == value]:
                            results.append(value)
                    else:
                        add_value(others, name, value)
            return results, others, labels

        def describe(outcome):
            if "jump" in outcome:
                return "jump " + outcome["jump"]
            parts = ["result = %r" % (outcome["result"],)]
            parts.extend("%s = %r" % (name, value) for name, value in sorted(outcome["set"].items()))
            return ", ".join(parts)

        def outcomes_after(node):
            results, others, labels = look_ahead(node)
            defaults = dict((name, values[0]) for name, values in others.items())
            outcomes = []

            if results:
                # One more result that matches nothing the script checks for, for its "else".
                if not (True in results and False in results and len(results) == 2):
                    results = results + [OTHER if [v for v in results if v is None] else None]
                outcomes = [{"result": value, "set": defaults} for value in results]
            elif others:
                outcomes = [{"result": None, "set": defaults}]

            for name, values in sorted(others.items()):
                for value in values[1:]:
                    changed = dict(defaults)
                    changed[name] = value
                    outcomes.append({"result": outcomes[0]["result"], "set": changed})

            if not outcomes:
                # Nothing to go on (RUN-020): carry on with no result, and try each place the script
                # may go from here.
                outcomes = [{"result": None, "set": {}}]
                outcomes.extend({"jump": label} for label in labels if renpy.has_label(label))

            return outcomes

        def skip_interaction(ctx):
            """Gets past an interaction that cannot be played, by deciding how it turned out."""
            finding("stuck", "info", "finding.stuck", {})
            node = renpy.game.script.namemap.get(ctx.current)
            outcomes = outcomes_after(node) if node is not None else [{"result": None, "set": {}}]
            outcome = outcomes[choose("skip", [describe(o) for o in outcomes])]

            # From here on the game is in a state the tool made up (RUN-021).
            state["speculative"] = True
            if "jump" in outcome:
                renpy.jump(outcome["jump"])
            for name, value in outcome["set"].items():
                setattr(store, name, value)
            return outcome["result"]

        def screen_buttons(ctx):
            found = []

            def visit(d):
                if isinstance(d, renpy.display.behavior.Button) and getattr(d, "action", None) is not None:
                    words = []

                    def collect(child):
                        if isinstance(child, renpy.text.text.Text):
                            words.append("".join(i for i in child.text if isinstance(i, str)))

                    d.visit_all(collect)
                    for text in words:
                        check_text(text)
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
            return skip_interaction(ctx)

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
            for label, value in items:
                check_text(label)
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

        # ------------------------------------- checks that rendering would have made (ARCH-007)
        #
        # Nothing is drawn or played, so a missing picture, a missing sound or a broken text tag would
        # pass unnoticed. Each is looked for here, at the moment the statement runs, using the engine's
        # own functions.

        reported = set()

        def problem(cls, message_id, params, key):
            """Reports something wrong at the current statement, once, and lets the story carry on."""
            filename, line = here()
            if (cls, filename, line, key) in reported:
                return
            reported.add((cls, filename, line, key))
            finding(cls, "error", message_id, params, filename, line)

        def loadable(filename, directory):
            try:
                return renpy.loader.loadable(filename, directory=directory)
            except TypeError:
                return renpy.loader.loadable(filename)  # Older engines take no directory.

        def spoken_name(name):
            return " ".join(name) if isinstance(name, (tuple, list)) else str(name)

        # Undefined images (ERR-004): the engine calls this when a show or scene names no known image.
        earlier_missing_show = config.missing_show

        def missing_show(name, what, layer):
            if state["starts"] and not state["finished"]:
                problem("undefined-image", "finding.undefined_image", {"name": spoken_name(name)}, spoken_name(name))
            if earlier_missing_show is not None:
                return earlier_missing_show(name, what, layer)
            return False

        config.missing_show = missing_show

        # Image files that cannot be loaded (ERR-003). The files an image needs are collected the same
        # way the engine's lint collects them: by asking each displayable what it would preload.
        def files_of(displayable):
            files = []

            def collect(image):
                files.extend(image.predict_files())

            previous = renpy.display.predict.image
            renpy.display.predict.image = collect
            try:
                displayable.visit_all(lambda d: d.predict_one())
            except Exception:
                pass
            finally:
                renpy.display.predict.image = previous
            return [f for f in files if isinstance(f, str)]

        def check_shown(tag):
            scene_lists = renpy.game.context().scene_lists
            for layer in scene_lists.layers:
                for entry in scene_lists.layers[layer]:
                    if entry.tag == tag and entry.displayable is not None:
                        for filename in files_of(entry.displayable):
                            if not loadable(filename, "images"):
                                problem("missing-file", "finding.missing_file", {"file": filename}, filename)

        original_show = renpy.show

        def show(name, *args, **kwargs):
            rv = original_show(name, *args, **kwargs)
            if state["starts"] and not state["finished"]:
                parts = tuple(name.split()) if isinstance(name, str) else tuple(name)
                tag = kwargs.get("tag") or (parts[0] if parts else None)
                if tag is not None:
                    check_shown(tag)
            return rv

        renpy.show = show
        if config.show is original_show:
            config.show = show

        # Audio and movie files that cannot be loaded (ERR-003).
        def audio_files(filenames, channel):
            if isinstance(filenames, str):
                filenames = [filenames]
            rv = []
            for filename in filenames or []:
                if not isinstance(filename, str):
                    continue
                try:
                    # Strips "<from 2.0 to 5.0>" and similar from the front of the name.
                    filename = renpy.audio.audio.get_channel(channel).split_filename(filename, False)[0]
                except Exception:
                    pass
                if isinstance(filename, str) and filename and not filename.startswith("<"):
                    rv.append(filename)
            return rv

        def checked_audio(original):
            def wrapper(filenames, channel="music", *args, **kwargs):
                if state["starts"] and not state["finished"]:
                    missing = [f for f in audio_files(filenames, channel) if not loadable(f, "audio")]
                    for filename in missing:
                        problem("missing-file", "finding.missing_file", {"file": filename}, filename)
                    if missing:
                        return None  # Asking the engine to play it would only fail later, off the story's path.
                return original(filenames, channel, *args, **kwargs)
            return wrapper

        renpy.audio.music.play = checked_audio(renpy.audio.music.play)
        renpy.audio.music.queue = checked_audio(renpy.audio.music.queue)

        original_movie_cutscene = renpy.movie_cutscene

        def movie_cutscene(filename, *args, **kwargs):
            if state["starts"] and isinstance(filename, str) and not loadable(filename, "audio"):
                if not loadable(filename, "images"):
                    problem("missing-file", "finding.missing_file", {"file": filename}, filename)
                    return False
            return original_movie_cutscene(filename, *args, **kwargs)

        renpy.movie_cutscene = movie_cutscene

        # Text tags (ERR-005). Interpolation errors need no check: the engine raises on them.
        def check_text(text):
            if not isinstance(text, str) or "{" not in text:
                return
            try:
                error = renpy.text.extras.check_text_tags(text, check_unclosed=True)
            except TypeError:
                error = renpy.text.extras.check_text_tags(text)  # Older engines always check for unclosed tags.
            except Exception as failure:
                error = str(failure)
            if error:
                problem("bad-text", "finding.bad_text", {"problem": error, "text": text[:200]}, text)

        original_display_say = renpy.character.display_say

        def display_say(who, what, *args, **kwargs):
            if state["starts"] and not state["finished"]:
                check_text(who)
                check_text(what)
            return original_display_say(who, what, *args, **kwargs)

        renpy.character.display_say = display_say

        # A menu that offers nothing (ERR-008). A menu that uses a set runs out of choices on purpose.
        original_menu_statement = renpy.exports.menu

        def menu_statement(items, set_expr, *args, **kwargs):
            if state["starts"] and not state["finished"] and not set_expr:
                offered = False
                for item in items:
                    try:
                        if item[2] is not None and renpy.python.py_eval(item[1]):
                            offered = True
                    except Exception:
                        offered = True
                if not offered and [item for item in items if item[2] is not None]:
                    problem("no-choice", "finding.no_choice", {}, "menu")
            return original_menu_statement(items, set_expr, *args, **kwargs)

        renpy.exports.menu = menu_statement

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

            text = "%s: %s" % (type(error).__name__, error)
            if "pygame" in type(error).__module__ and ("ideo" in str(error) or "isplay" in str(error)):
                # The game asked for something that needs a real screen, such as the clipboard. That is
                # a limit of testing without a window, not a fault in the game (ERR-012).
                finding("needs-display", "info", "finding.needs_display", {"message": text}, trace=trace)
                next_path("needs display")

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
            if label_runs:
                state["labels"] = labels_to_start()
            emit("start", seed=seed, map=script_map(), labels=list(state["labels"]))

            # Handed-over paths and label runs all begin at the first statement of the story; a snapshot
            # is taken there, so that each can start without restarting the engine.
            state["need_root"] = bool(state["resume"] or state["labels"])
            if state["resume"]:
                start_prefix(state["resume"].pop(0))
            elif story_done:
                state["need_root"] = True
                state["labels_only"] = True

        config.start_callbacks.append(started)

        # A project in development can reload itself when a script file changes on disk. A reload in the
        # middle of a run restarts the game under the harness's feet, so it is switched off (RUN-023).
        renpy.set_autoreload(False)

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
