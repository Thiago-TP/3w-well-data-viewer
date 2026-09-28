"""The application's own appearance: a theme installed into Qt and pyqtgraph, and the width of a tooltip.

One call settles both halves of the viewer's appearance, so that the windows and
the plots inside them can never be painted from two different ideas of what the
background is. ``apply`` also tells Qt which color scheme it is in, which is what
makes the pieces this application does not paint itself (the window frames, the
native folder dialog, the message boxes) follow along.

A mode is ``light``, ``dark``, or ``system`` for the desktop's own choice. The
choice is remembered between runs; ``--theme`` overrides it for one run.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from html import escape

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QObject, QRectF, QSettings, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtGui import Qt as GuiQt  # ``mightBeRichText`` is on QtGui's Qt, not QtCore's
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QProxyStyle,
    QStyle,
    QTabBar,
    QToolTip,
    QWidget,
)

from overlap_viewer.backend import theme
from overlap_viewer.backend.theme import Theme

SETTINGS = ("real-instance-viewer", "3W Real Instances Viewer")  # organization, application
THEME_KEY = "appearance/theme"

# Qt's own name for each mode. ``Unknown`` is not a failure: it is what tells Qt
# to stop overriding the desktop and report the scheme the desktop asks for,
# which is exactly what ``system`` means here.
SCHEMES = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}


def saved_mode(default: str = "system") -> str:
    """The mode remembered from the last run, or ``default`` if none is."""
    mode = QSettings(*SETTINGS).value(THEME_KEY, default)
    return mode if mode in theme.MODES else default


def save_mode(mode: str) -> None:
    """Remember ``mode`` for the next run."""
    QSettings(*SETTINGS).setValue(THEME_KEY, mode)


def resolve(mode: str) -> str:
    """The theme ``mode`` asks for, after telling Qt which scheme it is in.

    Qt is told first and read back second, because under ``system`` the answer
    is Qt's to give: the override has to be lifted before the desktop's own
    choice shows through again. The scheme is only ever written when it differs
    from the one in force, so that applying a mode the application is already in
    does not announce a change that has not happened.
    """
    app = QApplication.instance()
    if app is None:  # a scripted run without a GUI: nothing to ask
        return mode if mode in theme.THEMES else "light"
    hints = app.styleHints()
    wanted = SCHEMES.get(mode, Qt.ColorScheme.Unknown)
    if hints.colorScheme() != wanted:
        hints.setColorScheme(wanted)
    if mode in theme.THEMES:
        return mode
    return "dark" if hints.colorScheme() == Qt.ColorScheme.Dark else "light"


def qt_palette(colors: Theme) -> QPalette:
    """The window chrome of one theme, as Qt wants it.

    Every role is stated rather than left to the style's own defaults: a palette
    half filled in is how a dark window ends up with the text color of a light
    one, which is the clash this module exists to prevent.
    """
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: colors.window,
        QPalette.ColorRole.WindowText: colors.text,
        QPalette.ColorRole.Base: colors.base,
        QPalette.ColorRole.AlternateBase: colors.alternate_base,
        QPalette.ColorRole.ToolTipBase: colors.tooltip,
        QPalette.ColorRole.ToolTipText: colors.tooltip_text,
        QPalette.ColorRole.Text: colors.text,
        QPalette.ColorRole.Button: colors.button,
        QPalette.ColorRole.ButtonText: colors.text,
        QPalette.ColorRole.BrightText: colors.highlight_text,
        QPalette.ColorRole.Link: colors.link,
        QPalette.ColorRole.LinkVisited: colors.link,
        QPalette.ColorRole.Highlight: colors.highlight,
        QPalette.ColorRole.HighlightedText: colors.highlight_text,
        QPalette.ColorRole.PlaceholderText: colors.faint,
        QPalette.ColorRole.Mid: colors.border,
        QPalette.ColorRole.Midlight: colors.alternate_base,
        QPalette.ColorRole.Dark: colors.border,
        QPalette.ColorRole.Shadow: colors.border,
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.HighlightedText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors.faint))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(colors.alternate_base)
    )
    return palette


# There is deliberately no application stylesheet. One used to state the few
# rules a palette cannot (a toolbar's bottom line, its separators, the tab
# pane's frame, no frame around status-bar items, the tooltip border), and it
# cost at three points: setting it polishes every widget again, close to two
# seconds with the pages built; every widget created under it is polished
# through the stylesheet engine, which slows every page's layout; and a widget
# under a stylesheet does not follow a palette change until it is polished
# again, so a theme switch left the chrome in the old mode's text color unless
# the sheet was set once more. Fusion draws all of those from the palette by
# itself, close enough, and follows ``QApplication.setPalette`` at once.


def apply(mode: str) -> Theme:
    """Put ``mode`` in force everywhere: Qt, pyqtgraph and the current theme.

    Returns the theme now in force, whose ``name`` says which of the two a
    ``system`` mode resolved to.
    """
    colors = theme.use(resolve(mode))
    pg.setConfigOptions(background=colors.plot_background, foreground=colors.plot_foreground)
    app = QApplication.instance()
    if app is not None:
        app.setPalette(qt_palette(colors))
    return colors


@contextmanager
def theme_scope(name: str | None) -> Iterator[Theme]:
    """Put the theme ``name`` in force for what is built inside the block, then give the old one back.

    For a window that keeps a theme of its own while the application keeps
    another: every color is read from ``theme.current()`` when an item is
    built, and pyqtgraph's foreground when an axis is, so a window that builds
    its plots inside this block gets its own colors and leaves everyone else's
    alone. Only the theme and pyqtgraph's options move; the palette of the
    window is the caller's to set. ``None``, or the theme already in force,
    changes nothing.
    """
    previous = theme.current()
    if name is None or name == previous.name:
        yield previous
        return
    colors = theme.use(name)
    pg.setConfigOptions(background=colors.plot_background, foreground=colors.plot_foreground)
    try:
        yield colors
    finally:
        theme.use(previous.name)
        pg.setConfigOptions(
            background=previous.plot_background, foreground=previous.plot_foreground
        )


# -- Check boxes that can be seen in the dark -------------------------------------

# Fusion edges a check box with a darker shade of the window behind it, which
# on a light window is a clear grey line and on a dark one very nearly black
# on near-black: an empty box all but disappears, and an unticked item of a
# list shows no box at all. The dark mode gets an edge of its own, in the
# weight of text the theme keeps for a hint, which reads as a box without
# competing with the labels beside it.
CHECKS = (
    QStyle.PrimitiveElement.PE_IndicatorCheckBox,
    QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
)


class _VisibleChecks(QProxyStyle):
    """Fusion, with a check box edged in the theme's own colors in the dark mode.

    Whether the mode is dark, and the colors of the edge, are read off the
    palette the box is painted with rather than off the theme in force, so
    that a window keeping a theme of its own gets the edge its own theme asks
    for (``qt_palette`` puts the hint's weight in ``PlaceholderText`` and the
    border in ``Mid``).
    """

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        super().drawPrimitive(element, option, painter, widget)
        palette = option.palette
        if element not in CHECKS or palette.color(QPalette.ColorRole.Window).lightness() >= 128:
            return
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        role = QPalette.ColorRole.PlaceholderText if enabled else QPalette.ColorRole.Mid
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(palette.color(QPalette.ColorGroup.Active, role), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Fusion's own box is drawn a pixel inside the rectangle it is given.
        box = QRectF(option.rect).adjusted(1.5, 1.5, -1.5, -1.5)
        painter.drawRoundedRect(box, 1.5, 1.5)
        painter.restore()


def install_style() -> None:
    """Paint the application with Fusion, whose every color comes from the palette, and visible checks."""
    app = QApplication.instance()
    if app is None or isinstance(app.style(), _VisibleChecks):
        return
    app.setStyle(_VisibleChecks("Fusion"))


# -- The width of a tooltip -------------------------------------------------------

# Qt bounds a tooltip by the screen, not by what a person can read: the long
# explanations this viewer puts in its tooltips come out as a band of text
# around half the screen wide (some 960 px on a 1920 monitor), one or two lines
# tall, which is hard to read and covers the very control it explains. There is
# no width to set, so a tooltip is laid out in a table cell of a fixed width,
# which Qt's rich text honors exactly.
TOOLTIP_WIDTH_PX = 460
_BOUNDED = '<table class="tip"'  # how a tooltip that has been through this says so


def bounded_tooltip(text: str) -> str:
    """One tooltip laid out in a column ``TOOLTIP_WIDTH_PX`` wide, if it needs one.

    A tooltip that already fits on one line of that width is returned
    untouched: fixing the width of a cell fixes it in both directions, and
    "Show every well again" in a 460-pixel box would be mostly box. Plain text
    is escaped, since several tooltips name a placeholder such as
    ``<class>/<instance>.parquet`` that rich text would swallow, and its line
    breaks are kept; text that is already rich passes through. Bounding an
    already bounded tooltip returns it unchanged, so the filter below can set
    the result back on the widget without looping.
    """
    if not text.strip() or text.startswith(_BOUNDED):
        return text
    rich = GuiQt.mightBeRichText(text)
    if not rich:
        metrics = QFontMetrics(QToolTip.font())
        if all(metrics.horizontalAdvance(line) <= TOOLTIP_WIDTH_PX for line in text.split("\n")):
            return text
    body = text if rich else escape(text).replace("\n", "<br>")
    return f'{_BOUNDED}><tr><td width="{TOOLTIP_WIDTH_PX}">{body}</td></tr></table>'


# -- How long a tooltip stays -----------------------------------------------------

# Qt takes a tooltip down after ten seconds and a little more per character,
# which is less than it takes to read the longer explanations this viewer puts
# in them. A tooltip here stays until the pointer leaves what it explains (or a
# key or a button is pressed), as Qt already does on those; only the clock is
# taken away. The duration is a timer's, so the longest a timer can run, some
# twenty-four days, is what never means.
TOOLTIP_FOREVER_MS = 2**31 - 1


class _ToolTips(QObject):
    """Bounds the width of every tooltip set on a widget, and keeps every tooltip up until the pointer moves off.

    **Width.** A tooltip reaches a reader three ways, and this catches the
    common one. Setting one on a widget sends it ``ToolTipChange``, and a tool
    button copies the tooltip of its action, so one filter on the application
    covers every ``setToolTip`` of every page. The two paths it cannot see, a
    tab's tooltip and a ``QToolTip.showText`` of a widget's own, call
    ``bounded_tooltip`` themselves.

    **Duration.** A widget passes its own ``toolTipDuration`` when it shows its
    tooltip, so it is given one that never runs out just before. The item of a
    list and the tab of a tab bar are shown by Qt with the default duration
    and no way to set another, so those two are shown here instead, over the
    item or the tab they belong to; a widget that shows tooltips of its own
    (the availability map) passes ``TOOLTIP_FOREVER_MS`` itself.
    """

    def eventFilter(self, watched, event) -> bool:
        if not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind == QEvent.Type.ToolTipChange:
            bounded = bounded_tooltip(watched.toolTip())
            if bounded != watched.toolTip():
                watched.setToolTip(bounded)
        elif kind == QEvent.Type.ToolTip:
            return self._show(watched, event)
        return False

    @staticmethod
    def _show(watched: QWidget, event) -> bool:
        """Show the tooltip of an item or a tab with no clock on it; let Qt show a widget's own."""
        view = watched.parent()
        if isinstance(view, QAbstractItemView) and watched is view.viewport():
            index = view.indexAt(event.pos())
            text = index.data(Qt.ItemDataRole.ToolTipRole) if index.isValid() else None
            rect = view.visualRect(index)
        elif isinstance(watched, QTabBar):
            index = watched.tabAt(event.pos())
            text = watched.tabToolTip(index) if index >= 0 else None
            rect = watched.tabRect(index)
        else:
            if watched.toolTipDuration() != TOOLTIP_FOREVER_MS:
                watched.setToolTipDuration(TOOLTIP_FOREVER_MS)
            return False
        if not text:
            return False  # nothing to say: Qt takes down whatever is up
        QToolTip.showText(event.globalPos(), str(text), watched, rect, TOOLTIP_FOREVER_MS)
        return True


_tooltips: _ToolTips | None = None


def install_tooltips() -> None:
    """Bound the tooltips of this application and take their clock away, once, before its widgets are built."""
    global _tooltips
    app = QApplication.instance()
    if app is None or _tooltips is not None:
        return
    _tooltips = _ToolTips(app)
    app.installEventFilter(_tooltips)
