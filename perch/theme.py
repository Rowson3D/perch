"""Design tokens - the single source of every color, font and spacing value.

Every window (widget, dialogs, menus, tooltips, setup) is built from these.
See docs/design-system.md for how they are used.
"""

# Surfaces (darkest -> lightest)
BG = "#15171c"  # widget + dialog background
SURFACE = BG
HIST_BG = "#181a20"  # history graph well
FIELD = "#1b1e25"  # inputs, lists
ROW = "#1e2128"  # cards
RAISED = "#262a33"  # secondary buttons
HOVER = "#30353f"  # hovered rows / buttons
PRESSED = "#1f232b"
TIP_BG = "#101217"  # tooltips, menus, toasts (floating layers)
BORDER = "#2a2e38"
TIP_BORDER = "#343946"

# Text
FG = "#e7e9ef"
MUTED = "#8a8f9c"
GREY = "#5b606c"  # disabled / unknown

# Accent + status
ACCENT = "#7aa2ff"
ACCENT_HOVER = "#93b3ff"
ACCENT_DIM = "#2b3858"  # selection background
ON_ACCENT = "#0b0d12"  # text on accent buttons
GREEN, GREEN_DIM = "#3ecf6e", "#1d4a30"
RED, RED_DIM, RED_HOVER = "#f0585b", "#5a2526", "#f37477"
AMBER, AMBER_DIM = "#f0b429", "#5a4618"
GREY_DIM = "#2b2e36"
TRACK, MARK, UTIL_LINE = "#2e323d", "#aeb3c0", "#7f8696"

# Typography (Segoe UI = Windows system font)
FONT = "Segoe UI"
FONT_SEMI = "Segoe UI Semibold"
FS = (FONT, 8)  # small / hints
F = (FONT, 9)  # body
FB = (FONT_SEMI, 9)  # body emphasis
FT = (FONT_SEMI, 10)  # card / tooltip title
FH = (FONT_SEMI, 12)  # dialog heading
FD = (FONT_SEMI, 16)  # display (setup window)
MONO = ("Consolas", 9)

# Spacing (px)
PAD = 16  # dialog padding
GAP = 8  # between related controls
SECTION = 14  # between sections

# Widget geometry
BAR_W, BAR_H, HIST_H = 280, 6, 24
