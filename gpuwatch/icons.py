"""App / tray icons, drawn with Pillow so there are no image files to ship."""

from PIL import Image, ImageDraw

from gpuwatch import theme as T

COLORS = {"free": T.GREEN, "busy": T.RED, "held": T.AMBER, "unknown": T.MUTED}
HEIGHTS = (0.50, 0.80, 0.38)


def render(size=256, colors=("free", "busy", "free"), margin=0.20):
    s = max(size, 64) * 4  # draw large, then downsample for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=T.FIELD, outline=T.TIP_BORDER, width=max(1, s // 48)
    )
    m, gap = s * margin, s * 0.07
    bw = (s - 2 * m - 2 * gap) / 3
    bottom, room = s - m, s - 2 * m
    for i, (c, h) in enumerate(zip(colors, HEIGHTS, strict=True)):
        x0 = m + i * (bw + gap)
        d.rounded_rectangle([x0, bottom - room * h, x0 + bw, bottom], radius=bw * 0.28, fill=COLORS[c])
    return img.resize((size, size), Image.LANCZOS)


def tray_image(status):
    """status: 'free' (something free), 'busy' (nothing free) or 'unknown'."""
    return render(64, (status,) * 3, margin=0.16)


def save_ico(path):
    render(256).save(
        path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )


def photo(size=64):
    from PIL import ImageTk

    return ImageTk.PhotoImage(render(size))
