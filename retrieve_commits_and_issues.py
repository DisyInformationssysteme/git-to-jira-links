#!/usr/bin/env python3

"""Retrieve all commits from a given git repository which map to JIRA
issues and write a todo file with links which need to be added to
JIRA.

"""

import argparse
import subprocess as sp
import os
import sys
import re
import logging
import time
import dulwich.repo
import dulwich.diff_tree
logging.basicConfig(level=logging.WARNING,
                    format=' [%(levelname)-7s] (%(asctime)s) %(filename)s::%(lineno)d %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')


parser = argparse.ArgumentParser()
parser.add_argument("repository_paths", nargs='*',
                    help="The path to the directory containing the repository to process")
parser.add_argument("--previous",
                    help="The path to the previous todo file with entries that should not be processed again")
parser.add_argument("-o", "--output", default="tasks.todo",
                    help="The path to the todo file to write")
parser.add_argument("--oneline", action="store_true",
                    help="Fake git oneline output")
parser.add_argument("--with-files", action="store_true",
                    help="also add output of all files affected by the commit")
parser.add_argument("--with-files-and-sizes", action="store_true",
                    help="also add output of the sizes of all files affected by the commit, implies --with-files, EXPENSIVE/SLOW")
parser.add_argument("--debug", action="store_true",
                    help="Set log level to debug")
parser.add_argument("--info", action="store_true",
                    help="Set log level to info")
parser.add_argument("--test", action="store_true",
                    help="Run tests")


JIRA_ID_MATCHER = re.compile(rb"(?:[^A-Z]*)([A-Z]+-[0-9]+)", flags=re.MULTILINE)


def get_jira_issue(commit_message):
    """retrieve the jira issue referenced in the commit message

    >>> get_jira_issue(b"BAH-123: ")
    {b'BAHN-123'}
    >>> messages = (
    ... b"this is jira issue named plainly BAH-123",
    ... b"BAH-123 plainly at the beginning",
    ... b"in parens (BAH-123)",
    ... b"(BAH-123) at the beginning",
    ... b"after a colon :BAH-123",
    ... b"Merged from \\FOO-4325 foo.\\n\\nsvn path=/foo/trunk/; revision=12345\\n"
    ... )
    >>> issuesets = (get_jira_issue(i) for i in messages)
    >>> issues = set()
    >>> for issueset in issuesets:
    ...     for issue in issueset: issues.add(issue)
    >>> sorted(list(issues))
    [b'FOO-4325', b'BAH-123']
    >>> get_jira_issue(b"there is no issue here")
    set()
    >>> with open("tomatch.txt", "rb") as f: data = f.read().splitlines()
    >>> missed = list(i for i in (None if get_jira_issue(i) else i for i in data) if i is not None)
    >>> len(missed)
    0
    >>> for i in missed:
    ...   print(i)
    >>> with open("missed-strings.txt", "rb") as f: data = f.read().splitlines()
    >>> missed = list(i for i in (None if get_jira_issue(i) else i for i in data) if i is not None)
    >>> len(missed)
    0
    >>> for i in missed:
    ...   print(i)
    """
    start = 0
    match = JIRA_ID_MATCHER.search(commit_message[start:])
    issues = set()
    while match:
        issues.add(match.group(1))
        start += match.end(1)
        match = JIRA_ID_MATCHER.search(commit_message[start:])
    return issues


def get_commit_ids_and_messages(repo_path, limit=1):
    """Get up to limit commits in the given repo_path.

    >>> list(get_commit_ids_and_messages(".", limit=None))[-1] # the root commit of this repo
    (b'723faf63a951eaed6de595973f23dbdfb67acba7', b'add Python skelleton\\n', 1518450170)
    """
    repo = dulwich.repo.Repo(repo_path)
    walker = repo.get_graph_walker()
    commit_ids = []
    n = 0
    while limit is None or n < limit:
        c = walker.next()
        if c is None:
            logging.debug("No more commits from walker %s", walker)
            break
        yield (c, repo.get_object(c).message, repo.get_object(c).commit_time)
        n += 1


def get_commit_ids_and_files(repo_path, limit=1, withsizes=False):
    """Get up to limit commits in the given repo_path.

    >>> list(get_commit_ids_and_files(".", limit=None))[-1] # the root commit of this repo
    (b'723faf63a951eaed6de595973f23dbdfb67acba7', [b'retrieve_commits_and_issues.py'], [2044])
    """
    repo = dulwich.repo.Repo(repo_path)
    walker = repo.get_graph_walker()
    commit_ids = []
    n = 0
    while limit is None or n < limit:
        c = walker.next()
        if c is None:
            break
        commit = repo.get_object(c)
        if commit.parents:
            prev_tree = repo.get_object(commit.parents[0]).tree
        else:
            prev_tree = None
        files = []
        sizes = []
        delta = dulwich.diff_tree.tree_changes(repo, prev_tree, commit.tree, want_unchanged=False)
        for x in delta:
            if x.new.path is None:
                continue
            files.append(x.new.path)
            if not withsizes:
                sizes.append(0)
                continue
            try:
                obj = repo.get_object(x.new.sha)
                data = obj.data
                length = (len(data) if data is not None else 0)
            except Exception as e:
                logging.error("Cannot get data from file %s with sha %s", x.new.path, x.new.sha)
                length = 0
            sizes.append(length)
        logging.debug("filechange: %s: %s, %s", c, files, sizes)
        yield (c, files, sizes)
        n += 1


def epochtime_to_isodate(commit_time):
    """
    >>> epochtime_to_isodate(1518450170)
    '2018-02-12'
    """
    return time.strftime("%Y-%m-%d", time.gmtime(commit_time)) # this is equivalent to %F from libc


def get_issue_references(repo_path, limit=1, withfiles=False, withsizes=False):
    """get all issue references and their commit IDs.

    >>> list(get_issue_references(".", limit=None))[-1:] # the first commit which referenced a jira issue
    >>> list(get_issue_references(".", limit=None, withfiles=True))[-1:] # the first commit which referenced a jira issue
    """
    commits = get_commit_ids_and_messages(repo_path, limit)
    files = (get_commit_ids_and_files(repo_path, limit, withsizes=withsizes) if withfiles else None)
    matches = []
    bytime = []
    try:
        c = next(commits)
        f = (next(files) if withfiles else None)
    except:
        c, f = None, None
    while c is not None:
        commit_id, message, commit_time = c
        if withfiles:
            commit_files = f[1]
            commit_sizes = f[2]
        else:
            commit_files = []
            commit_sizes = []
        bytime.append((commit_time, commit_id, message, commit_files, commit_sizes))
        try:
            c = next(commits)
        except Exception as e:
            logging.debug("%s: no more commits: %s", e, commits)
            break
        try:
            f = (next(files) if withfiles else None)
        except Exception as e:
            logging.debug("%s: no more files: %s", e, files)
            break
    bytime.sort()
    for commit_time, commit_id, message, files, sizes in reversed(bytime):
        isodate = epochtime_to_isodate(commit_time).encode("utf-8")
        # a commit might reference multiple issues
        issues = get_jira_issue(message)
        for issue in issues:
            if withfiles:
                yield (commit_id, issue, isodate, message, files, sizes)
            else:
                yield (commit_id, issue, isodate, message)

            
def format_todo_entry(commit_id, issue, isodate, message, files=None, sizes=None):
    """
    >>> format_todo_entry(b'123456', b'TEST-123', b'2018-03-12', b'initial version which can \\nfind issues in actual commits TEST-123\\n')
    >>> format_todo_entry(b'123456', b'TEST-123', b'2018-03-12', b'initial version which can \\nfind issues in actual commits TEST-123\\n', [b'retrieve_commits_and_issues.py', b'MOO'])
    >>> format_todo_entry(b'123456', b'TEST-123', b'2018-03-12', b'initial version which can \\nfind issues in actual commits TEST-123\\n', [b'retrieve_commits_and_issues.py', b'MOO'], [3769, 423])
    """
    if files is not None:
        if sizes is not None:
            filesandsizes = zip(files, (str(i).encode() for i in sizes))
            return b' '.join([commit_id, issue, isodate,
                              b":" + b":".join(b",".join(i) for i in filesandsizes) + b":",
                              message.replace(b'\n', b'---')])
        else:
            return b' '.join([commit_id, issue, isodate, b":" + b":".join(files) + b":", message.replace(b'\n', b'---')])
    else:
        return b' '.join([commit_id, issue, isodate, message.replace(b'\n', b'---')])


def get_commit_id_and_issue_from_todo_line(line):
    """
    >>> get_commit_id_and_issue_from_todo_line(b'123 TEST-123 initial version which can ---find issues in actual commits TEST-123---')
    """
    return (tuple(line.split()[:2]) if line.split()[1:] else None)
    
            
def main(args):
    if args.oneline and args.output:
        logging.error("Cannot output a todo file with oneline format.")
        sys.exit(1)
    
    previous = set()
    if args.previous:
        with open(args.previous, "rb") as f:
            for line in f:
                previous.add(get_commit_id_and_issue_from_todo_line(line))
        logging.info("read previous file %s", args.previous)
    if args.oneline:
        for commit_id, issue, isodate, message in get_issue_references(i, limit=None):
            print(str(commit_id[:11], encoding="utf-8"), str(message.splitlines()[0], encoding="utf-8"))
    elif args.with_files or args.with_files_and_sizes:
        with open(args.output, "wb") as f:
            for i in args.repository_paths:
                for commit_id, issue, isodate, message, files, sizes in get_issue_references(i, limit=None, withfiles=True, withsizes=args.with_files_and_sizes):
                    if not (commit_id, issue) in previous:
                        f.write(format_todo_entry(commit_id, issue, isodate, message, files, sizes) + b'\n')
    else:
        with open(args.output, "wb") as f:
            for i in args.repository_paths:
                for commit_id, issue, isodate, message in get_issue_references(i, limit=None):
                    if not (commit_id, issue) in previous:
                        f.write(format_todo_entry(commit_id, issue, isodate, message) + b'\n')
        logging.info("wrote todo file %s", args.output)


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
