"""The colours of everything RenPyTester shows that is not a terminal (spec GUI-015).

The HTML report and the window are meant to look like two parts of one program, so both take
their colours from here and nowhere else. There is a set for light surroundings and one for dark.
"""

import subprocess
import sys

LIGHT = {
    "page": "#f6f5f1", "card": "#ffffff", "ink": "#1d1f24", "soft": "#5d6470", "line": "#dcdad2",
    "error": "#b3261e", "warning": "#9a5b00", "info": "#1f5fa8", "ok": "#1e6b3a", "possible": "#6b4aa0",
    "code": "#f0eee8",
    # The purple of the icon, for the one thing on a screen that is the thing to press.
    "accent": "#5c4ac4", "accent-hover": "#4c3cab", "accent-ink": "#ffffff", "accent-soft": "#e7e3f8",
}
DARK = {
    "page": "#16181d", "card": "#1f2229", "ink": "#e8e6e1", "soft": "#a2a8b3", "line": "#363a44",
    "error": "#ff8a80", "warning": "#f0b45a", "info": "#86b7f5", "ok": "#7fd49b", "possible": "#c3a6f2",
    "code": "#14161a",
    "accent": "#8f7ff0", "accent-hover": "#a396f4", "accent-ink": "#14161a", "accent-soft": "#35305a",
}


def css_variables(colours):
    """The colours as CSS custom properties, for the HTML report."""
    return " ".join("--%s: %s;" % (name, value) for name, value in colours.items())


def system_is_dark():
    """True when the system is set to show programs dark. Where that cannot be told, False."""
    try:
        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            with key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            answer = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=2)
            return answer.stdout.strip().lower() == "dark"
    except Exception:
        pass
    return False
