# Spike 4: spike 3 plus `call screen` handling: buttons on screen are explored like menu choices.
# Throwaway code (spec milestone M0).

init -999 python:
    import os
    import json
    import time
    import sys
    _rt_path = os.environ.get("RENPYTESTER_EVENTS")
    _rt_t0 = time.time()

    def _rt_emit(**kw):
        if not _rt_path:
            return
        kw["t"] = round(time.time() - _rt_t0, 3)
        with open(_rt_path, "a") as f:
            f.write(json.dumps(kw, default=str) + "\n")

    _rt_emit(ev="init", renpy=list(renpy.version_tuple), py=sys.version.split()[0])

init 999 python hide:
    import traceback
    import renpy.execution as ex
    import renpy.display.core as core

    state = {
        "starts": 0,
        "interacts": 0,
        "menus": 0,
        "covered": set(),
        "path": [int(i) for i in os.environ.get("RENPYTESTER_PATH", "").split(",") if i != ""],
        "taken": [],
    }

    def is_game_node(node):
        fn = node.filename.replace("\\", "/")
        return not (fn.startswith("renpy/") or fn.startswith("common/"))

    def story_nodes():
        # Everything in the game's files, minus init-time code, other languages' translation
        # blocks and test cases: what a playthrough could execute.
        skip = set()
        def mark(n):
            skip.add(n.name)
        for _prio, node in renpy.game.script.initcode:
            if hasattr(node, "get_children"):
                node.get_children(mark)
        rv = {}
        for n in renpy.game.script.all_stmts:
            if not is_game_node(n) or n.name in skip:
                continue
            if type(n).__name__ in ("Testcase", "EndTranslate", "TranslateString", "TranslatePython",
                                    "TranslateBlock", "TranslateEarlyBlock", "Init", "EarlyPython"):
                continue
            if getattr(n, "language", None) is not None:
                continue
            if n.filename.replace("\\", "/").startswith("game/tl/"):
                continue
            rv[n.name] = n
        last = {}
        for n in rv.values():
            if n.filename not in last or n.linenumber >= last[n.filename].linenumber:
                last[n.filename] = n
        for n in last.values():
            if type(n).__name__ == "Return":
                del rv[n.name]
        return rv

    def finish(reason):
        nodes = story_nodes()
        total = set(nodes)
        hit = state["covered"] & total
        missed = sorted(set(
            (n.filename, n.linenumber, type(n).__name__) for k, n in nodes.items() if k not in hit))
        _rt_emit(
            ev="end", reason=reason, interacts=state["interacts"], menus=state["menus"],
            screens=state.get("screens", 0), paths=state["ex"]["paths"], errors=len(state["ex"]["errors"]),
            snap_kb=state["ex"]["snap_bytes"] // 1024, snap_s=round(state["ex"]["snap_time"], 3),
            load_s=round(state["ex"]["load_time"], 3), covered=len(hit), total=len(total), missed=missed[:40])
        renpy.quit()

    # 1. Coverage: check_infinite_loop is called once per executed statement.
    def per_statement():
        ctx = renpy.game.context()
        state["covered"].add(ctx.current)

    ex.check_infinite_loop = per_statement

    # 2. Interactions: never render, never wait.
    def fake_interact(
            self, clear=True, suppress_window=False, trans_pause=False, pause=None, pause_modal=False,
            **kwargs):
        state["interacts"] += 1
        ctx = renpy.game.context()
        kind = getattr(ctx.info, "_current_interact_type", None)
        if kind not in ("say", "menu", None) and os.environ.get("RENPYTESTER_VERBOSE"):
            node = renpy.game.script.lookup(ctx.current)
            _rt_emit(
                ev="interact", kind=kind, trans_pause=trans_pause, pause=pause,
                at="%s:%s" % (node.filename, node.linenumber))
        rv = None
        if kind == "screen":
            rv = fake_screen(ctx)
        if clear:
            ctx.scene_lists.replace_transient()
        self.end_transitions()
        self.restart_interaction = True
        ctx.mark_seen()
        ctx.scene_lists.shown_window = False
        if renpy.game.log is not None:
            renpy.game.log.did_interaction = True
        if rv is not None:
            return rv
        return kwargs.get("roll_forward") or True

    core.Interface.interact = fake_interact

    # 3. Menus: explore every choice of every menu once, snapshotting state in memory.
    import io as _io
    ex_state = {"stack": [], "scheduled": set(), "taken": {}, "forced": None, "paths": 0,
                "snap_bytes": 0, "snap_time": 0.0, "load_time": 0.0, "errors": []}
    state["ex"] = ex_state

    def snapshot():
        t = time.time()
        roots = renpy.game.log.freeze(None)
        buf = _io.BytesIO()
        renpy.loadsave.dump((roots, renpy.game.log), buf)
        ex_state["snap_time"] += time.time() - t
        ex_state["snap_bytes"] = max(ex_state["snap_bytes"], buf.tell())
        return buf.getvalue()

    def next_path(reason):
        ex_state["paths"] += 1
        _rt_emit(
            ev="path_end", n=ex_state["paths"], reason=reason, taken=state["taken"],
            pending=len(ex_state["stack"]))
        if not ex_state["stack"]:
            finish("explored")
        snap, pick, taken, path = ex_state["stack"].pop()
        ex_state["forced"] = pick
        ex_state["taken"] = taken
        state["taken"] = path
        state["starts"] = 1
        t = time.time()
        roots, log = renpy.loadsave.loads(snap)
        ex_state["load_time"] += time.time() - t
        log.unfreeze(roots, label="_after_load")

    def choose(decision_id, labels):
        """Returns the index to take at this decision point, scheduling the others."""
        done = ex_state["taken"].setdefault(decision_id, set())
        if ex_state["forced"] is not None:
            pick = ex_state["forced"]
            ex_state["forced"] = None
        else:
            open_here = [i for i in range(len(labels)) if i not in done]
            if not open_here:
                next_path("decision exhausted")
            fresh = [i for i in open_here if (decision_id, i) not in ex_state["scheduled"]]
            pick = (fresh or open_here)[0]
            later = [i for i in fresh if i != pick]
            if later and not os.environ.get("RENPYTESTER_NO_SNAPSHOT"):
                snap = snapshot()
                for i in later:
                    ex_state["scheduled"].add((decision_id, i))
                    taken_copy = dict((k, set(v)) for k, v in ex_state["taken"].items())
                    ex_state["stack"].append((snap, i, taken_copy, list(state["taken"])))
        ex_state["scheduled"].add((decision_id, pick))
        done.add(pick)
        state["taken"].append(labels[pick])
        return pick

    def fake_menu(items, *args, **kwargs):
        choices = [(label, value) for label, value in items if value is not None]
        state["menus"] += 1
        pick = choose(renpy.game.context().current, [c[0] for c in choices])
        value = choices[pick][1]
        if isinstance(value, renpy.ui.ChoiceReturn):
            value = value.value
        return value

    def screen_buttons(ctx):
        found = []
        def visit(d):
            if isinstance(d, renpy.display.behavior.Button) and getattr(d, "action", None) is not None:
                texts = []
                def text_of(x):
                    if isinstance(x, renpy.text.text.Text):
                        texts.append("".join(t for t in x.text if isinstance(t, str)))
                d.visit_all(text_of)
                found.append((" ".join(texts) or repr(d.action), d))
        sl = ctx.scene_lists
        for layer in sl.layers:
            for sle in sl.layers[layer]:
                d = sle.displayable
                if isinstance(d, renpy.display.screen.ScreenDisplayable):
                    d.update()
                d.visit_all(visit)
        return found

    def fake_screen(ctx):
        state["screens"] = state.get("screens", 0) + 1
        for _attempt in range(50):
            buttons = [(label, b) for label, b in screen_buttons(ctx) if renpy.is_sensitive(b.action)]
            if not buttons:
                node = renpy.game.script.lookup(ctx.current)
                _rt_emit(ev="stuck", at="%s:%s" % (node.filename, node.linenumber))
                next_path("stuck")
            pick = choose(ctx.current, [label for label, b in buttons])
            rv = renpy.run(buttons[pick][1].action)
            if rv is not None:
                return rv
        next_path("screen never returned")

    renpy.store.menu = fake_menu

    # 4. Exceptions: report and stop, instead of the engine's error screen.
    def handle_exception(self):
        e = sys.exc_info()[1]
        if e is None or not isinstance(e, Exception):
            raise
        node = renpy.game.script.lookup(self.current)
        _rt_emit(
            ev="exception", type=type(e).__name__, message=str(e),
            at="%s:%s" % (node.filename, node.linenumber),
            taken=state["taken"], traceback=traceback.format_exc().splitlines()[-4:])
        state["ex"]["errors"].append(1)
        next_path("exception")

    ex.Context.handle_exception = handle_exception

    # 5. End of path: the game restarting (back at _start) means the story ended.
    def started():
        state["starts"] += 1
        _rt_emit(ev="start", n=state["starts"])
        if state["starts"] > 1:
            next_path("returned to main menu")

    config.start_callbacks.append(started)
