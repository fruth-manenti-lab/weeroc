"""Small shared layout helpers (sizing only; no device logic)."""

import textwrap


def wrap_plot_title(title, width=62):
    """Wrap a long matplotlib title onto several lines instead of clipping it."""

    lines = []
    for line in str(title).splitlines() or [""]:
        lines.extend(textwrap.wrap(line, width=width, break_long_words=False) or [""])
    return "\n".join(lines)


def fit_special_text(spinbox, margin=44):
    """Widen a spinbox so its special-value text (e.g. "Keep current") is not clipped."""

    text = spinbox.specialValueText()
    needed = spinbox.fontMetrics().horizontalAdvance(text) + margin
    spinbox.setMinimumWidth(max(spinbox.minimumWidth(), needed))


def fit_controls_pane(split, scroll, controls, right_width=650):
    """Size a left-hand controls scroll area so its form needs no horizontal scrollbar."""

    needed = (controls.minimumSizeHint().width()
              + scroll.verticalScrollBar().sizeHint().width() + scroll.frameWidth() * 2 + 4)
    scroll.setMinimumWidth(needed)
    split.setSizes([max(needed, controls.sizeHint().width() + 30), right_width])
