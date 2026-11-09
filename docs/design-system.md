# Design system

Every window Perch shows is built from **one set of tokens** and **one set of components**, so they all look and behave the same: cards, dialogs, menus, tooltips and setup. Future Rowson3D desktop tools should reuse the same tokens.

## Tokens: `perch/theme.py`

Colors, fonts, spacing and sizes live only in `theme.py`. **Never hard-code a color, font or padding anywhere else.** This includes icons, which `icons.py` draws from the same tokens.

| Group | Tokens |
|---|---|
| Surfaces | `BG`/`SURFACE` (windows) · `FIELD` (inputs) · `ROW` (card rows, tiles) · `RAISED` (buttons) · `HOVER` · `TIP_BG` (menus, tooltips, toasts) · `BORDER` |
| Text | `FG` · `MUTED` (secondary) · `GREY` (disabled/unknown) |
| Accent | `ACCENT` · `ACCENT_HOVER` · `ACCENT_DIM` (selection, badges) · `ON_ACCENT` |
| Status | `GREEN` ok / free / up · `AMBER` warning / held · `RED` bad / in use / down · `GREY` unknown; each has a `_DIM` fill, and `RED_HOVER` is for danger buttons |
| Type | `FS` 8pt hints · `F` 9pt body · `FB` 9pt emphasis · `FT` 10pt titles · `FH` 12pt headings · `FD` 16pt display · `MONO` |
| Spacing | `PAD` 16 window padding · `SECTION` 14 between sections · `GAP` 8 between related controls |

## Theme: `perch/style.py`

`style.apply(root)` installs the dark ttk theme for every ttk widget in the process, including custom-drawn checkboxes and sliders. Use these named styles instead of passing colors directly:

- **Labels:** `Heading`, `Display`, `Section` (uppercase group titles), `Muted`, `Hint`, `Info`, `Success`, `Error`
- **Labels on tiles and cards:** `Card`, `CardTitle`, `CardMuted`, `CardBadge` (e.g. the "SOON" pill)
- **Buttons:**
  - default (secondary)
  - `Accent.TButton`: the primary action, one per window
  - `Danger.TButton`: destructive confirmations
  - compact variants for tiles: `Small`, `SmallAccent` and `SmallDanger`
- **Containers:** `Card.TFrame` and `Card.TCheckbutton`, for grouped content and tiles

`style.dark_titlebar(win)` makes Windows draw the native title bar dark.

## Components: `perch/components.py`

| Need | Use | Never |
|---|---|---|
| A window | `Dialog(master, title, heading=, subtitle=)`. Fill `.content`, call `.buttons(...)`, then `.show(near=)` | a bare `Toplevel` |
| A list of things to manage | `ListManager(...)`: a list plus Add, Edit, Remove, Move up and Move down | a custom list window |
| Ask yes/no | `confirm(master, title, message, ok=, danger=)` | `tkinter.messagebox` |
| Tell the user something | `alert(master, title, message, kind=)` | `tkinter.messagebox` |
| A menu | `PopupMenu(root).command(...).check(...).separator().popup(x, y)` | `tk.Menu` (it can't be themed on Windows) |
| Details on hover | `app.tip.show(key, card_win, row, build)` (a `HoverCard`) | a custom tooltip |
| Form rows and sections | `form_row`, `section`, `spin`, `int_of` | ad-hoc grids |
| Card header buttons | `icon_button(parent, "+", command)` | plain labels with clicks |
| Motion | `hatch_in` (a new card drops in) and `fly_away` (a removed card drifts off) | instant pop-in or removal |

## Cards: `perch/cards/base.py`

Every card subclasses `Card`, which provides the parts all cards share:

- the borderless window, with the header: title, summary, then **+** **⋯** **–**;
- dragging, and snapping to screen edges and other cards;
- the right-click menu, which ends with the shared items (Card settings, Always on top, Hide, Your perch, Hatch, Quit);
- the settings window, with the card's own sections first and the shared **CARD** section last (title, always on top, opacity).

A card type only describes its rows, its data and its own settings.

## Layout rules

- **Window structure:** heading → optional muted subtitle → content → separator → footer.
- **Footer buttons** are right-aligned, and the **primary action is rightmost**. Cancel, Back and other secondary buttons go to its left. Version, tips or status text go on the far left.
- **Forms** are a two-column grid: the label on the left, the control filling the right, and an optional hint in a third column.
- **Section titles** use the `Section` style in UPPERCASE, with `SECTION` spacing above.
- **Status is shown as dot + word + color** (FREE, IN USE, HELD, UP, DOWN), never by color alone.
- **Card rows** sit on `ROW` with this structure: dot · name · badge · value on the first line; then an optional graph on `HIST_BG`; then a muted detail line.
- **Tiles** (Your perch, the hatch gallery) are `Card.TFrame` in a uniform two-column grid. The "add" tile is a dashed outline that lights up in `ACCENT` on hover.
- **Floating layers** (tooltips, menus, toasts) use `TIP_BG` with a 1px `TIP_BORDER` frame.
- **Words:** cards are **hatched** and **fly away**. Everything else uses plain verbs: Add, Edit, Remove, Settings.
