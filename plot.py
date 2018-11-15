#!/usr/bin/env python3

import pylab as pl
import math
import matplotlib
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("datafiles", nargs='*',
                    help="The path to the datafiles to plot")
parser.add_argument("-t", "--title", default="Files touched per issue over time",
                    help="The title to use for the plot.")
parser.add_argument("--ylabel", default="number of files",
                    help="The label to use for the y-axis (vertical).")
parser.add_argument("-o", "--output", default="",
                    help="The output file. The file extension determines the type. If not set, the plot is shown interactively.")

args = parser.parse_args()

files_affected_log = []
files_affected = []
with open(args.datafiles[0] if args.datafiles else "files-affected-by-time-with-issue-only-bugs.dat") as f:
    for i,n in enumerate(f):
        n = n.split()[-1]
        files_affected_log.append((i, math.log(1 + int(n), 10)))
        files_affected.append((i, int(n)))

pl.hexbin(*zip(*files_affected_log), norm=matplotlib.colors.LogNorm(), gridsize=50)
cb = pl.colorbar()
cb.set_label('number of matching issues')
pl.ylabel(args.ylabel)
pl.xlabel("issues sorted by time, oldest first")
locs, labels = pl.yticks()
explabels = [10**(loc) - 1 for loc in locs]
pl.yticks(locs, [int(i) if i >= 0.01 else "" for i in explabels])
pl.ylim(0, max(j for i,j in files_affected_log))
pl.title(args.title)
running_median = []
running_95 = []
radius = 500
nissues = len(files_affected)
for i, n in files_affected:
    window = [v for idx,v in files_affected[max(0, i - radius):min(nissues, i + radius)]]
    running_median.append(sorted(window)[int(len(window)*0.5)])
    running_95.append(sorted(window)[int(len(window)*0.95)])
pl.plot([math.log(i, 10) for i in running_median], label="running median", lw=2, color="magenta")
pl.plot([math.log(i, 10) for i in running_95], label="95% line", lw=2, color="orange")
pl.legend()
if args.output:
    pl.savefig(args.output, bbox_inches="tight")
else:
    pl.show()
