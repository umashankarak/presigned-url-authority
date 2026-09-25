#!/usr/bin/env python3
"""Figure 2 - share of determinable sites showing each over-grant, with Wilson 95% CIs.
Counts come from analyze_phase2.py output. Writes figure2_overgrant.pdf and .png."""
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# (label, over-granted count, determinable sites)
ROWS = [
    ("Write-anywhere POST key scope", 0, 164),
    ("Unbounded POST upload", 37, 193),
    ("Unbounded PUT upload", 30, 37),
    ("Key from raw user input", 24, 139),
    ("No resource-level authorization", 50, 86),
    ("Raw user key and no\nresource-level authorization", 17, 71),
]

def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * p, 100 * max(0.0, c - h), 100 * min(1.0, c + h)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
fig, ax = plt.subplots(figsize=(7.2, 3.6))
ys = list(range(len(ROWS)))[::-1]
for y, (label, k, n) in zip(ys, ROWS):
    p, lo, hi = wilson(k, n)
    ax.barh(y, p, height=0.55, color="#9DB8D3", edgecolor="#2F4F6F", lw=0.8)
    ax.errorbar(p, y, xerr=[[p - lo], [hi - p]], fmt="none", ecolor="#222222", capsize=3, lw=1)
    ax.text(hi + 1.5, y, f"{p:.1f}%  ({k}/{n})", va="center", fontsize=8.5)

ax.set_yticks(ys)
ax.set_yticklabels([r[0] for r in ROWS])
ax.set_xlim(0, 105)
ax.set_xlabel("Share of determinable sites (%), with 95% Wilson interval")
ax.spines[["top", "right"]].set_visible(False)
ax.grid(axis="x", color="#DDDDDD", lw=0.6)
ax.set_axisbelow(True)
fig.tight_layout()
fig.savefig("figure2_overgrant.pdf", bbox_inches="tight")
fig.savefig("figure2_overgrant.png", dpi=600, bbox_inches="tight")
print("wrote figure2_overgrant.pdf and figure2_overgrant.png")
