# Design system

Every window Perch shows is built from **one set of tokens** and **one set of components**, so they all look and behave the same. Future Rowson3D desktop tools should reuse the same tokens.

## Tokens: `perch/theme.py`

Colors, fonts, spacing and sizes live only in `theme.py`. **Never hard-code a color, font or padding anywhere else.**

| Group | Tokens |
|---|---|
| Surfaces | `BG`/`SURFACE` (windows) · `FIELD` (inputs) · `ROW` (cards) · `RAISED` (buttons) · `HOVER` · `TIP_BG` (menus, tooltips, toasts) · `BORDER` |
| Text | `FG` · `MUTED` (secondary) · `GREY` (disabled/unknown) |
| Accent | `ACCENT` · `ACCENT_HOVER` · `ACCENT_DIM` (selection) · `ON_ACCENT` |
| Status | `GREEN` free · `RED` in use / error · `AMBER` held · `GREY` unknown; each has a `_DIM` fill |
| Type | `FS` 8pt hints · `F` 9pt body · `FB` 9pt emphasis · `FT` 10pt titles · `FH` 12pt headings · `FD` 16pt display · `MONO` |
| Spacing | `PAD` 16 window padding · `SECTION` 14 between sections · `GAP` 8 between related controls |

## Theme: `perch/style.py`

`style.apply(root)` installs the dark ttk theme for every ttk widget in the process. Use these named styles instead of passing colors directly:

- **Labels:** `Heading`, `Display`, `Section` (uppercase group titles), `Muted`, `Hint`, `Info`, `Success`, `Error`, `Card`
- **Buttons:**
  - default (secondary)
  - `Accent.TButton`: primary action, one per window
  - `Danger.TButton`: destructive confirmations
- **Containers:** `Card.TFrame` and `Card.TCheckbutton`, for grouped content

`style.dark_titlebar(win)` makes Windows draw the native title bar dark.

## Components: `perch/components.py`

| Need | Use | Never |
|---|---|---|
| A window | `Dialog(master, title, heading=, subtitle=)`. Fill `.content`, call `.buttons(...)`, then `.show(near=)` | a bare `Toplevel` |
| Ask yes/no | `confirm(master, title, message, ok=, danger=)` | `tkinter.messagebox` |
| Tell the user something | `alert(master, title, message, kind=)` | `tkinter.messagebox` |
| A menu | `PopupMenu(root).command(...).check(...).separator().popup(x, y)` | `tk.Menu` (it can't be themed on Windows) |

## Layout rules

- **Window structure:** heading → optional muted subtitle → content → separator → footer.
- **Footer buttons** are right-aligned, and the **primary action is rightmost**. Cancel and other secondary buttons go to its left. Version or status text goes on the far left.
- **Forms** are a two-column grid: the label on the left, the control filling the right, and an optional hint in a third column.
- **Section titles** use the `Section` style in UPPERCASE, with `SECTION` spacing above.
- **Status is shown as dot + word + color** (FREE, IN USE, HELD), never by color alone.
- **Floating layers** (tooltips, menus, toasts) use `TIP_BG` with a 1px `TIP_BORDER` frame.
