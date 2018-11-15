#!/usr/bin/env python3

"""Link commits from a todo file to jira issues.
"""

import argparse
import subprocess as sp
import collections
import tempfile
import io
import netrc
import os
import os.path
import sys
import re
import json
import time
import logging
import functools
import array
import gpg
import dulwich.repo
import jira
logging.basicConfig(level=logging.WARNING,
                    format=' [%(levelname)-7s] (%(asctime)s) %(filename)s::%(lineno)d %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')


parser = argparse.ArgumentParser()
parser.add_argument("todofiles", nargs='*',
                    help="The path to the todo file to process")
parser.add_argument("-e", "--exclude-file", default="finished_tasks.log",
                    help="Exclude tasks from the given file, by default the same as the logfile to avoid creating duplicate links.")
parser.add_argument("-i", "--include-issues-file", # default="all-bugs.log",
                    help="Only include issues which are named in this file (one per line).")
parser.add_argument("--count-files-per-issue", action="store_true",
                    help="For each issue count the number of files it affected.")
parser.add_argument("--sum-filesizes-per-issue", action="store_true",
                    help="For each issue add the sizes of the files affected.")
parser.add_argument("--file-connections", action="store_true",
                    help="Correlate files with each other.")
parser.add_argument("--output-edgelist",
                    help="Write the edgelist into the given filepath. Used by --file-connections")
parser.add_argument("--output-nodelist",
                    help="Write the nodelist into the given filepath. Used by --file-connections")
parser.add_argument("--debug", action="store_true",
                    help="Set log level to debug")
parser.add_argument("--info", action="store_true",
                    help="Set log level to info")
parser.add_argument("--test", action="store_true",
                    help="Run tests")


def read_todo(filepath):
    """ Read the todo file
    
    >>> todofile = "issues-and-files.log"
    >>> list(read_todo(todofile))[:1]
    ['016add7c00f6da53ee3c36b227672b416419c972 TEST-123 2018-11-15 :README.org,0:correlate_files_per_issue.py,0:find_all_bugs.py,0:guix.scm,0:link_commits_to_issues.py,0:plot.py,0:retrieve_commits_and_issues.py,0:retrieve_repository_info.py,0: TEST-123 initial commit of public version---\\n']
    """
    with open(filepath) as f:
        for i in f:
            yield i

def process_taskline(taskline):
    """Retrieve issue_id and files from a taskline in a todo file.

    >>> process_taskline('454545648916166 FOO-12345 2018-03-12 :A,2:B,8:C,999: FOO-12345  foo------svn path=/foo/trunk/; revision=123---\\n')
    ('FOO-12345', '2018-03-12', ('A', 'B', 'C'), (2, 8, 999))
    """
    commit_id, issue_id, isodate, rest = taskline.split(" ", 3)
    files_string, title = rest.split(": ", 1)
    if files_string == ":":
        files, sizes = [], []
    else:
        files = files_string.split(':')[1:]
        try:
            sizes = tuple([int(f.split(",")[-1]) for f in files])
        except ValueError as e:
            logging.warn("Unparseable file name in taskline, contains colon (:). Faking all filesizes as 0. Taskline: %s, Error: %s", taskline, e)
            sizes = [0 for i in files]
        files = tuple([",".join(f.split(",")[:-1]) for f in files])
    shorttitle = title.split('---')[0]
    # if the title is too short, include the second non-empty line
    if len(shorttitle) < 20:
        shorttitle = " - ".join([i for i in title.split('---')
                                 if i.strip()][:2])
    return (issue_id, isodate, files, sizes)


def sum_filesizes_per_issue(changes):
    """Associate the files with their issues.

    >>> sum_filesizes_per_issue([('FOO-1111', '2018-03-12', ('A', 'B'), (1, 15)), ('FOO-1111', '2018-03-10', ('A', 'C'), (2, 5)), ('FOO-1112', '2018-03-11', ('A', 'D'), (2, 8))])
    [('2018-03-11:FOO-1112', 10), ('2018-03-12:FOO-1111', 23)]
    """
    issuedatelatest = {}
    mapped = {}
    for i in changes:
        issue = i[0]
        date = i[1]
        files = i[2]
        sizes = i[3]
        if issue not in issuedatelatest or issuedatelatest[issue] < date:
            issuedatelatest[issue] = date
        if issue not in mapped:
            mapped[issue] = 0
        for s in sizes:
            mapped[issue] += s
    # add the latest known edit date of the issue
    withdate = {}
    for key, value in mapped.items():
        date = issuedatelatest[key]
        withdate[date + ":" + key] = value
    return list(sorted(withdate.items()))


def aggregate_files_per_issue(changes):
    """Associate the files with their issues.

    >>> i = list(aggregate_files_per_issue([('FOO-1111', '2018-03-12', ('A', 'B'), (1, 15)), ('FOO-1111', '2018-03-10', ('A', 'C'), (2, 5)), ('FOO-1112', '2018-03-11', ('A', 'D'), (2, 8))]).items())
    >>> i.sort()
    >>> i
    [('2018-03-11:FOO-1112', ('A', 'D')), ('2018-03-12:FOO-1111', ('A', 'B', 'C'))]
    """
    issuedatelatest = {}
    mapped = {}
    for i in changes:
        issue = i[0]
        date = i[1]
        files = i[2]
        sizes = i[3]
        if issue not in issuedatelatest or issuedatelatest[issue] < date:
            issuedatelatest[issue] = date
        if issue not in mapped:
            mapped[issue] = set()
        for f in files:
            mapped[issue].add(f)
    for key, value in mapped.items():
        value = list(value)
        value.sort()
        mapped[key] = tuple(value)
    # add the latest known edit date of the issue
    withdate = {}
    for key, value in mapped.items():
        date = issuedatelatest[key]
        withdate[date + ":" + key] = value
    return withdate


def count_files_per_issue(aggregated):
    """Count the number of files for each issue.

    :param aggregated: {issue: [file, ...], ...}

    >>> i = count_files_per_issue(dict((('TEST-1111', ('A', 'B', 'C')), ('TEST-1112', ('A', 'D')))))
    >>> i.sort()
    >>> i
    [('TEST-1111', 3), ('TEST-1112', 2)]
    """
    return [(key, len(v)) for key, v in aggregated.items()]
    

def correlate_files_with_each_other(aggregated):
    """Calculate which files get are combined with which other files

    :param aggregated: {issue: [file, ...], ...}

    >>> known_files, edges, weights = correlate_files_with_each_other(dict((('TEST-1111', ('A', 'B', 'C')), ('TEST-1112', ('A', 'D')))))
    >>> known_files
    ('A', 'B', 'C', 'D')
    >>> [(i, tuple(j)) for i,j in edges]
    [(0, (0, 1, 2, 3)), (1, (0, 1, 2)), (2, (0, 1, 2)), (3, (0, 3))]
    >>> [(i, tuple(j)) for i,j in weights]
    [(0, (2, 1, 1, 1)), (1, (1, 1, 1)), (2, (1, 1, 1)), (3, (1, 1))]
    """
    edges = {}
    weights = {}
    # reference the files by an index in a list instead of referencing them directly to avoid having duplicate filenames in memory (dictionaries reference by content).
    known_files_to_index = {}
    known_files = []
    issuecount = len(aggregated.values())
    for i, files in enumerate(aggregated.values()):
        if len(files) > 300:
            logging.debug("skipping issue with more than 300 changed files since it would massively pollutes our data. Filecount: %s", len(files))
            continue
        if not i % 100: # every 100 steps
            logging.debug("step %s / %s, filecount: %s here / %s total", i, issuecount, len(files), len(known_files))
        for f in files:
            if f not in known_files_to_index:
                known_files_to_index[f] = len(known_files)
                known_files.append(f)
            fidx = known_files_to_index[f]
            if fidx not in edges:
                edges[fidx] = array.array("I") # unsigned integer
                weights[fidx] = array.array("I") # unsigned integer
            # use a temporary set for quick lookup, but store arrays for memory efficiency
            edgecounter = collections.Counter()
            edgeindex = {}
            for target, weight in zip(edges[fidx], weights[fidx]):
                edgecounter[target] = weight
            for i, target in enumerate(edges[fidx]):
                edgeindex[target] = i
            for g in files:
                if g not in known_files_to_index:
                    known_files_to_index[g] = len(known_files)
                    known_files.append(g)
                gidx = known_files_to_index[g]
                if gidx not in edgecounter:
                    edges[fidx].append(gidx)
                    weights[fidx].append(1)
                else:
                    weights[fidx][edgeindex[gidx]] += 1
                edgecounter[gidx] += 1
    for k in edges:
        v = edges[k]
        w = weights[k]
        edges[k] = array.array("I", sorted(v))
        weights[k] = array.array("I", sorted(w, key=lambda x: edges[x]))
    return tuple(known_files), tuple(sorted(list(edges.items()))), tuple(sorted(list(weights.items())))


def main(args):
    try:
        excluded = set(read_todo(args.exclude_file))
    except FileNotFoundError as e:
        logging.warn("Exclude file not found: %s", args.exclude_file)
        excluded = set()
    
    include_issues = set()
    if args.include_issues_file:
        try:
            with open(args.include_issues_file) as f:
                for line in f:
                    include_issues.add(line.strip())
        except FileNotFoundError as e:
            logging.warn("Include issues file not found: %s", args.include_issues_file)
    
    changes = []
    for i in args.todofiles:
        changes.extend([process_taskline(i)
                        for i in read_todo(i)
                        if not i in excluded])

    if args.include_issues_file:
        filtered = []
        for i in changes:
            if i and i[0] in include_issues:
                filtered.append(i)
        changes = filtered

    if args.count_files_per_issue:
        count = count_files_per_issue(
            aggregate_files_per_issue(changes))
        count.sort()
        for i in count:
            print(i[0] + " " + str(i[1]))
    elif args.sum_filesizes_per_issue:
        count = sum_filesizes_per_issue(changes)
        count.sort()
        for i in count:
            print(i[0] + " " + str(i[1]))
    elif args.file_connections:
        nodeout = (open(args.output_nodelist, "w") if args.output_nodelist else sys.stdout)
        edgeout = (open(args.output_edgelist, "w") if args.output_edgelist else sys.stdout)
        all_files, edges, weights = correlate_files_with_each_other(aggregate_files_per_issue(changes))
        print("Id Label", file=nodeout)
        for i, f in enumerate(all_files):
            print(i, f, file=nodeout)
        if args.output_nodelist:
            nodeout.close()
        print("------")
        print("Source Target Weight", file=edgeout)
        for (source, targets), (source, weights) in zip(edges, weights):
            for target, weight in zip(targets, weights):
                print(source, target, weight, file=edgeout)
        if args.output_edgelist:
            edgeout.close()
    else:
        logging.error("No command given. See %s --help", parser.prog)

    


# output test results as base60 number (for aesthetics)
def numtosxg(n):
    CHARACTERS = ('0123456789'
                  'ABCDEFGHJKLMNPQRSTUVWXYZ'
                  '_'
                  'abcdefghijkmnopqrstuvwxyz')
    s = ''
    if not isinstance(n, int) or n == 0:
        return '0'
    while n > 0:
        n, i = divmod(n, 60)
        s = CHARACTERS[i] + s
    return s


def _test(args):
    """  run doctests, can include setup. """
    from doctest import testmod
    tests = testmod()
    if not tests.failed:
        return "^_^ ({})".format(numtosxg(tests.attempted))
    else: return ":( "*tests.failed
    
if __name__ == "__main__":
    args = parser.parse_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    if args.info:
        logging.getLogger().setLevel(logging.INFO)
    if args.test:
        print(_test(args))
    else:
        main(args)
