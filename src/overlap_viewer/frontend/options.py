"""The *Options* button of a page or window: how it draws, behind one click.

A page keeps in view what picks the data it shows (a fault, a sensor, a well)
and the toggles of its side panels; the controls of how that data is drawn sit
in option bars this button shows and hides together. They start hidden, so
that a first look at a page is the plot rather than its controls, and stay as
they are left until the button is clicked again.

The bars are hidden whole, never their controls one by one: a page's own rules
for which of its controls are on show (a box only the pair map uses, one only
the DTW representation) keep working underneath, and come back as they were
when the options do.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QToolBar, QWidget

OPTIONS_TIP = (
    "Show or hide the options of this page: how what it shows is drawn. What picks the data "
    "stays in view either way."
)


class OptionsAction(QAction):
    """A checkable *Options* action that shows and hides the parts handed to ``add``.

    A part is anything with ``setVisible``: a whole toolbar, or one action of
    a toolbar that also holds what stays in view.
    """

    def __init__(self, parent, tip: str = OPTIONS_TIP):
        super().__init__("Options", parent)
        self.setCheckable(True)
        self.setToolTip(tip)
        self._parts: list = []
        self.toggled.connect(self._show)

    def add(self, part):
        """Put ``part`` behind the button, hidden or shown as the options are now; returns it."""
        part.setVisible(self.isChecked())
        self._parts.append(part)
        return part

    def _show(self, shown: bool) -> None:
        for part in self._parts:
            part.setVisible(shown)


def toolbar(name: str) -> QToolBar:
    """A fixed toolbar, the kind every row of a page is made of."""
    bar = QToolBar(name)
    bar.setMovable(False)
    return bar


def bar_row(*bars: QWidget, trailing: QWidget | None = None) -> QWidget:
    """Toolbars side by side as one row, ``trailing`` pushed to its right end.

    Toolbars rather than one: what stays in view and what the options hide sit
    in different ones, so that hiding the options leaves the rest where it was.
    """
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    for bar in bars:
        layout.addWidget(bar, 0, Qt.AlignmentFlag.AlignLeft)
    layout.addStretch(1)
    if trailing is not None:
        layout.addWidget(trailing)
    return row
