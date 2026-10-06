# Spike 1: does the engine start a normal run with dummy video/audio, and can a loose .rpy hook in?
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
            f.write(json.dumps(kw) + "\n")
    _rt_emit(ev="init", renpy=list(renpy.version_tuple), py=sys.version, video=os.environ.get("SDL_VIDEODRIVER"))

init 999 python:
    def _rt_started():
        _rt_emit(ev="start")
    config.start_callbacks.append(_rt_started)

    _rt_count = [0]
    def _rt_interact():
        _rt_count[0] += 1
        _rt_emit(
            ev="interact", n=_rt_count[0], main_menu=renpy.context()._main_menu,
            renderer=renpy.get_renderer_info().get("renderer"), size=renpy.get_physical_size(),
            node=str(renpy.game.context().current))
        if _rt_count[0] >= 3:
            renpy.quit()
    config.start_interact_callbacks.append(_rt_interact)
