"""Shared colours and style-sheet helpers for the app's dark surface.

Qt style sheets set on a widget also apply to that widget's children, and Qt
parents tooltip labels to the widget they describe.  A rule written without a
selector therefore leaks into the tooltip (an unscoped ``max-width`` squeezed
one to a single word) and into standard edit menus.  :func:`scoped` keeps a
declaration block on the widget it was written for.
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap

WINDOW_BG = "#1E1F22"
PANEL_BG = "#2B2D31"
BUTTON_BG = "#45484F"
MUTED_TEXT = "#A3A6AD"

# Main's graphite palette. The old names stay as aliases so existing widgets
# keep importing them; the extra names let the ported stylesheet read like
# main's.
BG = WINDOW_BG
SURFACE = PANEL_BG
SURFACE_ALT = "#313338"
CONSOLE = "#18191C"
BORDER = "#3A3C42"
BORDER_STRONG = "#4A4D55"
CONTROL = BUTTON_BG

# Main's hover/pressed/disabled colours. Buttons change colour only, never
# size, so nothing moves under the pointer.
CONTROL_HOVER = "#555861"
CONTROL_PRESSED = "#3A3C42"
DISABLED_BG = "#323439"
TEXT = "#F2F3F5"
TEXT_SOFT = "#D4D6DA"
TEXT_MUTED = MUTED_TEXT
TEXT_DISABLED = "#7C7F87"
INFO = "#9DB8FF"
FOCUS = "#8AA4F0"
ACCENT = "#4863B8"
ACCENT_HOVER = "#5A76C9"
ACCENT_PRESSED = "#3D55A0"
DANGER = "#B5474B"
DANGER_HOVER = "#C75A5E"
DANGER_PRESSED = "#943A3D"
NOTE_BG = "#26282C"
SELECTION = ACCENT
PROGRESS = ACCENT_HOVER
PROGRESS_PAUSED = "#D4A017"
PROGRESS_DONE = "#4CAF50"
SUCCESS = "#6BCF7F"
WARNING = "#FFD93D"
ERROR = "#FF6B6B"
RADIUS = 6

# Menus are built by Qt in places no widget code can reach: a plain line
# edit's standard menu is shown with popup(), not through a Python override.
# These rules are therefore applied application-wide in app.main().
MENU_STYLE = (
    f"QMenu {{ background-color: {SURFACE}; color: {TEXT};"
    f" border: 1px solid {BORDER_STRONG}; padding: 4px; }}"
    f"QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}"
    f"QMenu::item:selected {{ background-color: {SELECTION}; }}"
    f"QMenu::item:disabled {{ color: {TEXT_DISABLED}; }}"
    f"QMenu::separator {{ height: 1px; background: {BORDER_STRONG};"
    " margin: 4px 6px; }"
)

# Hover help sits on the app's dark surface rather than the platform's default
# light tooltip colour.
TOOLTIP_STYLE = (
    f"QToolTip {{ background-color: {SURFACE}; color: {TEXT};"
    f" border: 1px solid {BORDER_STRONG}; border-radius: 4px;"
    " padding: 5px 8px; }"
)


def scoped(selector, declarations):
    """Return a style-sheet rule scoped to *selector*.

    Use this for anything that can have children, so a size or background
    declaration cannot leak into a tooltip label or a context menu.
    """
    return f"{selector} {{ {declarations} }}"


# Style sheets can only show images stored in files. Main renders the check
# and minus glyphs from qtawesome once, so the boxes show a real mark instead
# of a flat colour. Successes are cached; a failure is retried next time.
_GLYPH_CACHE = {}
_CHECKBOX_IMAGE_CACHE = {}


def _glyph_path(icon_name, filename, color=TEXT, size=12):
    """Render *icon_name* to a PNG and return a QSS-friendly path, or ""."""
    cached = _GLYPH_CACHE.get(filename)
    if cached and os.path.isfile(cached):
        return cached
    # A cached path can point at a folder that has since been removed (tests
    # give each case its own data directory), so a missing file re-renders.
    _GLYPH_CACHE.pop(filename, None)
    try:
        import qtawesome as qta

        from kemonodownloader.kd_paths import data_directory, ensure_directory

        directory = ensure_directory(
            os.path.join(data_directory(), "theme"), "theme folder"
        )
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            pixmap = qta.icon(icon_name, color=color).pixmap(size * 2, size * 2)
            pixmap.setDevicePixelRatio(2.0)
            if not pixmap.save(path, "PNG"):
                return ""
        _GLYPH_CACHE[filename] = path.replace(os.sep, "/")
    except Exception:
        return ""
    return _GLYPH_CACHE[filename]


def _checkbox_image_path(filename, fill, border, icon_name=None, icon_color=TEXT):
    """Render a complete checkbox indicator to a PNG and return its path.

    The whole 16x16 box is drawn into the image, including its border.  A Qt
    style sheet indicator made only of background/border can leave the native
    Windows indicator visible underneath at some scale factors; an opaque
    image covers it completely and gives every state one consistent shape.
    """
    cached = _CHECKBOX_IMAGE_CACHE.get(filename)
    if cached and os.path.isfile(cached):
        return cached
    _CHECKBOX_IMAGE_CACHE.pop(filename, None)
    try:
        import qtawesome as qta

        from kemonodownloader.kd_paths import data_directory, ensure_directory

        directory = ensure_directory(
            os.path.join(data_directory(), "theme"), "theme folder"
        )
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(QPen(QColor(border), 1))
                painter.setBrush(QColor(fill))
                painter.drawRoundedRect(0, 0, 15, 15, 4, 4)
                if icon_name:
                    icon = qta.icon(icon_name, color=icon_color).pixmap(12, 12)
                    painter.drawPixmap(2, 2, icon)
            finally:
                painter.end()
            if not pixmap.save(path, "PNG"):
                return ""
        _CHECKBOX_IMAGE_CACHE[filename] = path.replace(os.sep, "/")
    except Exception:
        return ""
    return _CHECKBOX_IMAGE_CACHE[filename]


def button_states(hover=None, pressed=None):
    """Hover, pressed and disabled rules for a QPushButton.

    Appended to the shared button styles so inline backgrounds keep their
    base colour but still respond to the pointer, like main's theme. Coloured
    buttons (danger, reset) pass their own hover/pressed shades.
    """
    hover_bg = hover or CONTROL_HOVER
    pressed_bg = pressed or CONTROL_PRESSED
    return (
        scoped(
            "QPushButton:hover",
            f"background: {hover_bg}; border-color: {hover_bg};",
        )
        + scoped(
            "QPushButton:pressed",
            f"background: {pressed_bg}; border-color: {pressed_bg};",
        )
        + scoped(
            "QPushButton:disabled",
            f"background: {DISABLED_BG}; border-color: {DISABLED_BG};"
            f" color: {TEXT_DISABLED};",
        )
    )


def checkbox_style():
    """The app-wide QCheckBox indicator style.

    Every state is one complete rendered image, not a native indicator with a
    stylesheet border drawn over it.  This keeps a single box visible at every
    Windows scale factor.
    """
    unchecked = _checkbox_image_path(
        "checkbox_unchecked_2b2d31.png", PANEL_BG, BUTTON_BG
    )
    unchecked_hover = _checkbox_image_path(
        "checkbox_unchecked_hover_2b2d31.png", PANEL_BG, FOCUS
    )
    checked = _checkbox_image_path(
        "checkbox_checked_4863b8.png", ACCENT, ACCENT_HOVER, "fa5s.check"
    )
    minus = _checkbox_image_path(
        "checkbox_minus_4863b8.png", ACCENT, ACCENT_HOVER, "fa5s.minus"
    )
    disabled = _checkbox_image_path(
        "checkbox_disabled_323439.png", DISABLED_BG, DISABLED_BG
    )
    disabled_checked = _checkbox_image_path(
        "checkbox_disabled_checked_323439.png",
        DISABLED_BG,
        DISABLED_BG,
        "fa5s.check",
        TEXT_DISABLED,
    )
    disabled_minus = _checkbox_image_path(
        "checkbox_disabled_minus_323439.png",
        DISABLED_BG,
        DISABLED_BG,
        "fa5s.minus",
        TEXT_DISABLED,
    )

    def image(path):
        return f"image: url('{path}');" if path else "image: none;"

    return (
        f"QCheckBox {{ color: {TEXT}; spacing: 7px; background: transparent; }}"
        f"QCheckBox:disabled {{ color: {TEXT_DISABLED}; }}"
        "QCheckBox::indicator { width: 16px; height: 16px;"
        f" border: none; background: transparent; {image(unchecked)} }}"
        "QCheckBox::indicator:hover {"
        f" {image(unchecked_hover)} }}"
        "QCheckBox::indicator:checked {"
        f" {image(checked)} }}"
        "QCheckBox::indicator:indeterminate {"
        f" {image(minus)} }}"
        "QCheckBox::indicator:disabled {"
        f" {image(disabled)} }}"
        "QCheckBox::indicator:checked:disabled {"
        f" {image(disabled_checked)} }}"
        "QCheckBox::indicator:indeterminate:disabled {"
        f" {image(disabled_minus)} }}"
    )


def repolish(widget):
    """Re-apply the style sheet after a property it reads has changed."""
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def set_progress_state(bar, state):
    """Colour *bar* as paused, done, or normal (``None``)."""
    if bar.property("kdState") != state:
        bar.setProperty("kdState", state)
        repolish(bar)
    return bar


def style_progress_bar(bar):
    """Center the percentage and make its text white.

    QProgressBar draws its label from the palette, not from the style sheet's
    ``color``, so the palette has to say white explicitly.
    """
    palette = bar.palette()
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(role, QColor(TEXT))
    bar.setPalette(palette)
    bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return bar


def _button_and_input_styles():
    """Buttons, text inputs and their drop-down arrows."""
    down = _glyph_path("fa5s.chevron-down", "arrow-down_a3a6ad.png", TEXT_MUTED, 10)
    up = _glyph_path("fa5s.chevron-up", "arrow-up_a3a6ad.png", TEXT_MUTED, 10)
    down_off = _glyph_path(
        "fa5s.chevron-down", "arrow-down_7c7f87.png", TEXT_DISABLED, 10
    )
    up_off = _glyph_path("fa5s.chevron-up", "arrow-up_7c7f87.png", TEXT_DISABLED, 10)

    def image(path):
        return f"image: url('{path}');" if path else ""

    return (
        f"QPushButton {{ background: {CONTROL}; color: {TEXT};"
        f" border: 1px solid {CONTROL}; border-radius: {RADIUS}px;"
        " padding: 6px 12px; }"
        f"QPushButton:hover {{ background: {CONTROL_HOVER};"
        f" border-color: {CONTROL_HOVER}; }}"
        f"QPushButton:pressed {{ background: {CONTROL_PRESSED};"
        f" border-color: {CONTROL_PRESSED}; }}"
        f"QPushButton:focus {{ border-color: {FOCUS}; }}"
        f"QPushButton:disabled {{ background: {DISABLED_BG};"
        f" border-color: {DISABLED_BG}; color: {TEXT_DISABLED}; }}"
        'QPushButton[kdRole="primary"] { '
        f"background: {ACCENT}; border-color: {ACCENT};"
        " font-weight: bold; }"
        'QPushButton[kdRole="primary"]:hover { '
        f"background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}"
        'QPushButton[kdRole="primary"]:pressed { '
        f"background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}"
        'QPushButton[kdRole="danger"] { '
        f"background: {DANGER}; border-color: {DANGER}; }}"
        'QPushButton[kdRole="danger"]:hover { '
        f"background: {DANGER_HOVER}; border-color: {DANGER_HOVER}; }}"
        'QPushButton[kdRole="danger"]:pressed { '
        f"background: {DANGER_PRESSED}; border-color: {DANGER_PRESSED}; }}"
        'QPushButton[kdRole="primary"]:disabled, '
        'QPushButton[kdRole="danger"]:disabled { '
        f"background: {DISABLED_BG}; border-color: {DISABLED_BG};"
        f" color: {TEXT_DISABLED}; }}"
        'QPushButton[kdRole="icon"] { padding: 0px; }'
        f"QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit,"
        f" QTextEdit {{ background: {SURFACE}; color: {TEXT};"
        f" border: 1px solid {BORDER}; border-radius: {RADIUS}px;"
        f" selection-background-color: {SELECTION}; }}"
        "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 5px 8px; }"
        "QPlainTextEdit, QTextEdit { padding: 4px; }"
        "QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,"
        " QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus"
        f" {{ border-color: {FOCUS}; }}"
        "QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,"
        " QComboBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled"
        f" {{ color: {TEXT_DISABLED}; background: {DISABLED_BG}; }}"
        'QTextEdit[kdRole="console"], QPlainTextEdit[kdRole="console"] { '
        f"background: {CONSOLE}; padding: 6px; }}"
        "QComboBox::drop-down { border: none; width: 24px; }"
        f"QComboBox::down-arrow {{ {image(down)} width: 10px; height: 10px; }}"
        f"QComboBox::down-arrow:disabled {{ {image(down_off)} }}"
        f"QComboBox QAbstractItemView {{ background: {SURFACE};"
        f" border: 1px solid {BORDER_STRONG}; outline: none;"
        f" selection-background-color: {SELECTION}; padding: 2px; }}"
        "QSpinBox::up-button, QSpinBox::down-button,"
        " QDoubleSpinBox::up-button, QDoubleSpinBox::down-button"
        " { border: none; width: 18px; background: transparent; }"
        f"QSpinBox::up-arrow, QDoubleSpinBox::up-arrow"
        f" {{ {image(up)} width: 8px; height: 8px; }}"
        f"QSpinBox::down-arrow, QDoubleSpinBox::down-arrow"
        f" {{ {image(down)} width: 8px; height: 8px; }}"
        "QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled"
        f" {{ {image(up_off)} }}"
        "QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled"
        f" {{ {image(down_off)} }}"
    )


def _panel_and_list_styles():
    """Labels, group boxes, scroll areas and list/table surfaces."""
    return (
        f"QLabel {{ background: transparent; }}"
        f'QLabel[kdRole="muted"] {{ color: {TEXT_MUTED}; }}'
        f'QLabel[kdRole="soft"] {{ color: {TEXT_SOFT}; }}'
        f"QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px;"
        " margin-top: 14px; padding: 12px 10px 10px 10px;"
        " font-weight: bold; }"
        f"QGroupBox::title {{ subcontrol-origin: margin;"
        " subcontrol-position: top left; left: 10px; padding: 0 5px;"
        f" color: {TEXT}; }}"
        f'QFrame[kdRole="card"] {{ background: {SURFACE};'
        " border-radius: 8px; }"
        "QScrollArea { background: transparent; border: none; }"
        "QScrollArea > QWidget > QWidget { background: transparent; }"
        f"QListWidget, QListView, QTreeView, QTableView"
        f" {{ background: {SURFACE}; border: 1px solid {BORDER};"
        f" border-radius: {RADIUS}px; outline: none;"
        f" selection-background-color: {SELECTION};"
        f" selection-color: {TEXT}; }}"
        "QListWidget::item, QListView::item { border-radius: 4px; }"
        f"QListWidget::item:hover, QListView::item:hover"
        f" {{ background: {SURFACE_ALT}; }}"
        f"QListWidget::item:selected, QListView::item:selected"
        f" {{ background: {SELECTION}; }}"
        f"QTableView {{ alternate-background-color: {SURFACE_ALT};"
        " gridline-color: transparent; }"
        f"QHeaderView::section {{ background: {BORDER}; color: {TEXT};"
        " padding: 6px; border: none; }"
        f"QTableCornerButton::section {{ background: {BORDER};"
        " border: none; }"
    )


def _control_styles():
    """Progress bars, sliders, scroll bars, tabs and menus."""
    return (
        f"QProgressBar {{ background: {SURFACE}; border: 1px solid {BORDER};"
        f" border-radius: {RADIUS}px; text-align: center; color: {TEXT}; }}"
        f"QProgressBar::chunk {{ background: {PROGRESS}; border-radius: 5px; }}"
        f'QProgressBar[kdState="paused"]::chunk {{ background:'
        f" {PROGRESS_PAUSED}; }}"
        f'QProgressBar[kdState="done"]::chunk {{ background: {PROGRESS_DONE}; }}'
        f"QSlider::groove:horizontal {{ height: 6px; background: {SURFACE};"
        f" border: 1px solid {BORDER}; border-radius: 3px; }}"
        f"QSlider::sub-page:horizontal {{ background: {ACCENT};"
        " border-radius: 3px; }"
        f"QSlider::handle:horizontal {{ background: {TEXT};"
        f" border: 2px solid {ACCENT}; width: 12px; height: 12px;"
        " margin: -5px 0; border-radius: 8px; }"
        f"QSlider::handle:horizontal:hover {{ border-color: {ACCENT_HOVER}; }}"
        "QScrollBar:vertical { background: transparent; width: 12px;"
        " margin: 3px; }"
        "QScrollBar:horizontal { background: transparent; height: 12px;"
        " margin: 3px; }"
        f"QScrollBar::handle:vertical {{ background: {BORDER_STRONG};"
        " border-radius: 3px; min-height: 28px; }"
        f"QScrollBar::handle:horizontal {{ background: {BORDER_STRONG};"
        " border-radius: 3px; min-width: 28px; }"
        f"QScrollBar::handle:hover {{ background: {CONTROL_HOVER}; }}"
        "QScrollBar::add-line, QScrollBar::sub-line { width: 0px;"
        " height: 0px; }"
        "QScrollBar::add-page, QScrollBar::sub-page { background: none; }"
        f"QTabWidget::pane {{ border: none; background: {BG}; }}"
        "QTabBar { qproperty-drawBase: 0; }"
        f"QTabBar::tab {{ background: {SURFACE}; color: {TEXT_MUTED};"
        " padding: 9px 14px; margin-right: 3px; border-top-left-radius: 8px;"
        " border-top-right-radius: 8px; min-width: 70px;"
        " border-bottom: 2px solid transparent; }"
        f"QTabBar::tab:hover {{ background: {SURFACE_ALT}; color: {TEXT}; }}"
        f"QTabBar::tab:selected {{ background: {CONTROL}; color: {TEXT};"
        f" border-bottom-color: {FOCUS}; }}"
        f"QTabBar::tab:disabled {{ color: {TEXT_DISABLED}; }}"
        f"QMenu {{ background: {SURFACE}; border: 1px solid {BORDER_STRONG};"
        " padding: 4px; }"
        "QMenu::item { padding: 6px 18px; border-radius: 4px; }"
        f"QMenu::item:selected {{ background: {SELECTION}; }}"
        f"QMessageBox {{ background: {BG}; }}"
        f"QMessageBox QLabel {{ color: {TEXT}; }}"
        "QMessageBox QPushButton { min-width: 80px; }"
    )


def theme_stylesheet():
    """The app-wide graphite theme, ported from main."""
    return (
        f"* {{ color: {TEXT}; }}"
        f"QMainWindow, QDialog, QWidget#kdMain {{ background: {BG}; }}"
        f"QToolTip {{ background: {SURFACE}; color: {TEXT};"
        f" border: 1px solid {BORDER_STRONG}; border-radius: 4px;"
        " padding: 5px 8px; }"
        + _button_and_input_styles()
        + checkbox_style()
        + _panel_and_list_styles()
        + _control_styles()
    )
