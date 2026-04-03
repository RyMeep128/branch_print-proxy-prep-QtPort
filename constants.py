import os
import sys

from reportlab.lib.pagesizes import LETTER, A5, A4, A3, LEGAL

if getattr(sys, "frozen", False):
    cwd = os.path.dirname(os.path.abspath(sys.executable))
else:
    cwd = os.path.dirname(os.path.abspath(__file__))

page_sizes = {"Letter": LETTER, "A5": A5, "A4": A4, "A3": A3, "Legal": LEGAL}

card_size_with_bleed_inch = (2.72, 3.7)
card_size_without_bleed_inch = (2.48, 3.46)
card_ratio = card_size_without_bleed_inch[0] / card_size_without_bleed_inch[1]

low_dpi_warning_threshold = 300
