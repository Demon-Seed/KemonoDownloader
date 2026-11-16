"""Shared colours and style-sheet helpers for the app's dark surface.

Qt style sheets set on a widget also apply to that widget's children, and Qt
parents tooltip labels to the widget they describe.  A rule written without a
selector therefore leaks into the tooltip (an unscoped ``max-width`` squeezed
one to a single word) and into standard edit menus.  :func:`scoped` keeps a
declaration block on the widget it was written for.
"""

WINDOW_BG = "#1A2A44"
PANEL_BG = "#2A3B5A"
BUTTON_BG = "#4A5B7A"
MUTED_TEXT = "#8A9BB5"

# Menus are built by Qt in places no widget code can reach: a plain line
# edit's standard menu is shown with popup(), not through a Python override.
# These rules are therefore applied application-wide in app.main().
MENU_STYLE = (
    f"QMenu {{ background-color: {PANEL_BG}; color: white; }}"
    "QMenu::item:selected { background-color: rgba(74, 91, 122, 150); }"
    f"QMenu::item:disabled {{ color: {MUTED_TEXT}; }}"
    f"QMenu::separator {{ height: 1px; background: {BUTTON_BG};"
    " margin: 4px 6px; }"
)

# Hover help sits on the app's dark surface rather than the platform's default
# light tooltip colour.
TOOLTIP_STYLE = (
    f"QToolTip {{ background-color: {WINDOW_BG}; color: white;"
    f" border: 1px solid {BUTTON_BG}; }}"
)


def scoped(selector, declarations):
    """Return a style-sheet rule scoped to *selector*.

    Use this for anything that can have children, so a size or background
    declaration cannot leak into a tooltip label or a context menu.
    """
    return f"{selector} {{ {declarations} }}"
