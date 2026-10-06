# Spike 5: can translations be inspected for every language without switching language?
# Runs as a custom engine command, so no display is created and deferred tl scripts are loaded.

init 999 python:
    def _rt_tl_command():
        import os
        import json
        tr = renpy.game.script.translator
        out = {
            "languages": sorted(renpy.known_languages()), "current": renpy.game.preferences.language,
            "dialogue_total": len(tr.default_translates), "per_language": {}}
        for lang in out["languages"]:
            have = sum(1 for ident in tr.default_translates if (ident, lang) in tr.language_translates)
            st = tr.strings.get(lang)
            sample = None
            for ident in tr.default_translates:
                node = tr.language_translates.get((ident, lang))
                if node is not None:
                    block = getattr(node, "block", None) or [node]
                    src = tr.default_translates[ident]
                    sblock = getattr(src, "block", None) or [src]
                    sample = [
                        getattr(sblock[0], "what", None), getattr(block[0], "what", None),
                        node.filename, node.linenumber]
                    break
            out["per_language"][lang] = {
                "dialogue": have, "strings": len(st.translations) if st else 0, "sample": sample}
        # Substitution and tag checking without displaying anything.
        try:
            out["subst"] = renpy.substitute("Hello [missing_variable]")
        except Exception as e:
            out["subst"] = "raises %s: %s" % (type(e).__name__, e)
        out["tags_bad"] = renpy.check_text_tags("{b}unclosed")
        out["tags_ok"] = renpy.check_text_tags("{b}fine{/b}")
        out["display_created"] = renpy.display.interface is not None
        with open(os.environ["RENPYTESTER_EVENTS"], "a") as f:
            f.write(json.dumps(out) + "\n")
        return False

    renpy.arguments.register_command("renpytester_tl", _rt_tl_command)
