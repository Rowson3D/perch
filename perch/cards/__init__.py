"""Card types available in Perch. Add a new card by subclassing cards.base.Card and registering it here."""

from perch.cards.gpus import GpuCard
from perch.cards.sites import SitesCard

CARD_TYPES = {cls.TYPE: cls for cls in (SitesCard, GpuCard)}

# Shown in the hatch gallery as "Soon" so people can see where Perch is heading.
COMING_SOON = [
    ("pc", "This PC", "CPU, memory, disk and network for the computer you're on."),
    ("github", "GitHub", "Build status and open pull requests for your repositories."),
    (
        "custom",
        "Your own card",
        "Make a card from a website, an API or a script - visually or in a few lines of Python.",
    ),
]
