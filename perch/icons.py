"""App, tray and card-type icons, drawn with Pillow from the theme tokens (no image files to ship)."""

from PIL import Image, ImageDraw

from perch import theme as T

COLORS = {"free": T.GREEN, "busy": T.RED, "held": T.AMBER, "unknown": T.MUTED}
LEVEL_COLORS = {"ok": "free", "warn": "held", "bad": "busy", None: "unknown"}
HEIGHTS = (0.50, 0.80, 0.38)
SS = 4  # supersampling factor


def _canvas(size):
    s = max(size, 64) * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=T.FIELD, outline=T.TIP_BORDER, width=max(1, s // 48)
    )
    return img, d, s


def _finish(img, size):
    return img.resize((size, size), Image.LANCZOS)


def render(size=256, colors=("free", "busy", "free"), margin=0.20):
    """The Perch mark: three status bars."""
    img, d, s = _canvas(size)
    m, gap = s * margin, s * 0.07
    bw = (s - 2 * m - 2 * gap) / 3
    bottom, room = s - m, s - 2 * m
    for i, (c, h) in enumerate(zip(colors, HEIGHTS, strict=True)):
        x0 = m + i * (bw + gap)
        d.rounded_rectangle([x0, bottom - room * h, x0 + bw, bottom], radius=bw * 0.28, fill=COLORS[c])
    return _finish(img, size)


def card_icon(card_type, size=48):
    """Icon for a card type, used in the card list and the "Add a card" window."""
    if card_type == "gpus":
        return render(size)
    img, d, s = _canvas(size)
    w = max(2, s // 22)  # stroke width
    c = s / 2
    if card_type == "sites":  # a globe with a green "up" dot
        r = s * 0.28
        d.ellipse([c - r, c - r, c + r, c + r], outline=T.ACCENT, width=w)
        d.ellipse([c - r * 0.45, c - r, c + r * 0.45, c + r], outline=T.ACCENT, width=w)
        d.line([c - r, c, c + r, c], fill=T.ACCENT, width=w)
        dot = s * 0.11
        d.ellipse(
            [s * 0.72 - dot, s * 0.72 - dot, s * 0.72 + dot, s * 0.72 + dot], fill=T.GREEN, outline=T.FIELD, width=w
        )
    elif card_type == "jobs":  # a stopwatch
        r = s * 0.25
        cy = c + s * 0.04
        d.ellipse([c - r, cy - r, c + r, cy + r], outline=T.ACCENT, width=w)
        d.line([c, cy - r - s * 0.02, c, cy - r - s * 0.09], fill=T.ACCENT, width=w)
        d.line([c - s * 0.05, cy - r - s * 0.1, c + s * 0.05, cy - r - s * 0.1], fill=T.ACCENT, width=w)
        d.line([c, cy, c + r * 0.55, cy - r * 0.5], fill=T.GREEN, width=w)
        d.line([c, cy, c, cy - r * 0.7], fill=T.GREEN, width=w)
    elif card_type == "docker":  # stacked containers
        bw, bh = s * 0.17, s * 0.13
        boxes = [(0.30, 0.56), (0.49, 0.56), (0.395, 0.40)]
        for i, (x, y) in enumerate(boxes):
            color = T.GREEN if i == 2 else T.ACCENT
            d.rounded_rectangle([s * x, s * y, s * x + bw, s * y + bh], radius=s * 0.02, outline=color, width=w)
        d.line([s * 0.24, s * 0.74, s * 0.76, s * 0.74], fill=T.MUTED, width=w)
    elif card_type == "pc":  # a monitor
        d.rounded_rectangle([s * 0.22, s * 0.25, s * 0.78, s * 0.62], radius=s * 0.04, outline=T.MUTED, width=w)
        d.line([c, s * 0.62, c, s * 0.72], fill=T.MUTED, width=w)
        d.line([s * 0.38, s * 0.74, s * 0.62, s * 0.74], fill=T.MUTED, width=w)
    elif card_type == "github":  # a branch
        r = s * 0.06
        for x, y in ((0.36, 0.28), (0.36, 0.72), (0.66, 0.40)):
            d.ellipse([s * x - r, s * y - r, s * x + r, s * y + r], outline=T.MUTED, width=w)
        d.line([s * 0.36, s * 0.34, s * 0.36, s * 0.66], fill=T.MUTED, width=w)
        d.line([s * 0.66, s * 0.46, s * 0.66, s * 0.52, s * 0.40, s * 0.66], fill=T.MUTED, width=w, joint="curve")
    else:  # your own card: a sparkle
        pts = [
            (c, s * 0.22),
            (c + s * 0.07, c - s * 0.07),
            (s * 0.78, c),
            (c + s * 0.07, c + s * 0.07),
            (c, s * 0.78),
            (c - s * 0.07, c + s * 0.07),
            (s * 0.22, c),
            (c - s * 0.07, c - s * 0.07),
        ]
        d.polygon(pts, outline=T.MUTED, width=w)
    return _finish(img, size)


def tray_image(level):
    """level: 'ok', 'warn', 'bad' or None -> all three bars in that color."""
    return render(64, (LEVEL_COLORS.get(level, "unknown"),) * 3, margin=0.16)


def save_ico(path):
    render(256).save(
        path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )


def photo(size=64, master=None):
    from PIL import ImageTk

    return ImageTk.PhotoImage(render(size), master=master)


def card_photo(card_type, size=48, master=None):
    from PIL import ImageTk

    return ImageTk.PhotoImage(card_icon(card_type, size), master=master)
