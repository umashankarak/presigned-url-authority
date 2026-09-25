#!/usr/bin/env python3
"""Figure 1 - study pipeline for the presigned-URL paper.
Writes figure1_pipeline.pdf (vector, for LaTeX) and figure1_pipeline.png (600 dpi).
Edit the COUNTS dict if any Phase 1 number changes."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

COUNTS = {
    "hits": "187,485",       # hits.merged.jsonl
    "subsample": "23,994",   # subsample_report.json
    "filtered": "23,986",
    "deduped": "15,832",
    "post_pool": "3,291",
}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8.5})
fig, ax = plt.subplots(figsize=(7.2, 5.4))
ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

GREY, BLUE, GREEN, EDGE = "#F2F2F2", "#DCE9F5", "#E3F1E0", "#404040"

def box(x, y, w, h, text, color=GREY, bold_first=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                fc=color, ec=EDGE, lw=0.9))
    lines = text.split("\n")
    first, rest = lines[0], "\n".join(lines[1:])
    cy = y + h / 2
    if rest:
        ax.text(x + w / 2, cy + 2.2, first, ha="center", va="center",
                fontweight="bold" if bold_first else "normal")
        ax.text(x + w / 2, cy - 2.6, rest, ha="center", va="center", fontsize=7.6, linespacing=1.25)
    else:
        ax.text(x + w / 2, cy, first, ha="center", va="center",
                fontweight="bold" if bold_first else "normal")

def line(x1, y1, x2, y2):
    ax.plot([x1, x2], [y1, y2], color=EDGE, lw=0.9, solid_capstyle="butt")

def arrow(x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", lw=0.9, color=EDGE, shrinkA=0, shrinkB=0))

# Phase 1: corpus (top row, four boxes)
box(1, 83, 22.5, 13, "Code search\n17 terms, 8 languages\n%s hits" % COUNTS["hits"])
box(26, 83, 22.5, 13, "Capped subsample\nper term and language\n%s files" % COUNTS["subsample"])
box(51, 83, 22.5, 13, "Quality filter\nforks, archived removed\n%s files" % COUNTS["filtered"])
box(76, 83, 22.5, 13, "Deduplication\nMinHash near-duplicates\n%s files" % COUNTS["deduped"])
arrow(23.9, 89.5, 25.6, 89.5); arrow(48.9, 89.5, 50.6, 89.5); arrow(73.9, 89.5, 75.6, 89.5)

# Phase 2: two samples
line(87.25, 82.6, 87.25, 76.5)
line(87.25, 76.5, 26, 76.5); arrow(26, 76.5, 26, 72.4)
arrow(74, 76.5, 74, 72.4)
box(6, 59, 40, 13, "Blind sample (seed 42)\n400 of 2,307 primary + 100 of 13,525 low-signal\n\u00b115-line call-site windows", BLUE)
box(54, 59, 40, 13, "Targeted POST sample (seed 43)\n300 of %s POST-policy files,\nproportional by language; \u00b140-line windows" % COUNTS["post_pool"], BLUE)

arrow(26, 58.6, 26, 52.4); arrow(74, 58.6, 74, 52.4)
box(6, 40, 40, 12, "Junk filter + eligibility screen\n383 coded \u2192 260 eligible\n(all five dimensions)", BLUE)
box(54, 40, 40, 12, "Junk filter + eligibility screen\n238 coded \u2192 232 eligible\n(key scope and size bound)", BLUE)

# Analysis
line(26, 39.6, 26, 33.4); line(74, 39.6, 74, 33.4)
line(26, 33.4, 74, 33.4); arrow(50, 33.4, 50, 29.4)
box(22, 17, 56, 12, "Analysis\nindeterminate excluded from denominators; Wilson 95% intervals\nkey scope and size bound pooled; all other rates from blind sample")

# Phase 3
arrow(50, 16.6, 50, 11.4)
box(22, 0.5, 56, 10.5, "Ground-truth validation\nfive authority patterns on an author-owned S3 bucket", GREEN)

# phase labels
for y, t in [(89.5, "Corpus"), (65.5, "Sampling\n& coding"), (23, "Analysis"), (5.7, "Validation")]:
    ax.text(-1.5, y, t, ha="right", va="center", fontsize=7.6, style="italic", color="#555555")

fig.subplots_adjust(left=0.1, right=0.99, top=0.99, bottom=0.01)
fig.savefig("figure1_pipeline.pdf", bbox_inches="tight")
fig.savefig("figure1_pipeline.png", dpi=600, bbox_inches="tight")
print("wrote figure1_pipeline.pdf and figure1_pipeline.png")
