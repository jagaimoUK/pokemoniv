# Overlay check toggling and adjustable panel

Tapping an unchecked search/name button copies and checks it. Tapping a checked
button clears only that check, leaving the clipboard and copy count unchanged.
Long press copies again, increments the count, and sets the check. Search and
name checks remain independent. A tap resolves the current queued row by ID,
so a second tap before ListView redraw still clears the first tap's check.

The title is a move handle; the bottom-left arrow resizes the panel. Bottom-left
resizing makes horizontal growth possible when the panel initially opens on the
right edge. Width and height are stored in dp; position is stored relative to the
available space. Restore and movement clamp the panel inside the display. The
minimum is 196dp x 180dp where the display permits it; the maximum height is 80%
of the display or 640dp. Initial compact size remains the previous release's
default. Outside-tap collapse, Stop, the independent OCR bubble, CP/IV labels,
SQLite history, and the unfocused window behavior remain intact.

The original-project update package remains cumulative and hash guarded. The
controller's accepted baseline hashes include the previous CP compact release;
other unchanged files are skipped. It changes no Gradle settings or manifest
in the user's original project. Its build and backup/restore behavior is the
same as the previous package.

Robolectric tests exercise rapid repeat taps, independent search/name states,
unchanged clipboard on uncheck, long-press recopy counts, move/resize persistence,
offscreen bounds, outside collapse, and Stop. The demo harness is an isolated
build/test target. Actual device behavior and the user's original-project build
must be verified after applying the package.

Review: https://github.com/jagaimoUK/pokemoniv/pull/34
