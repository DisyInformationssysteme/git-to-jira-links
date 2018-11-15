#!/usr/bin/env python3

"""Retrieve repository info needed to relink jira issues and write it to a file.

"""

import argparse
import subprocess as sp
import os
import sys
import re
import json
import logging
import dulwich.repo
logging.basicConfig(level=logging.WARNING,
                    format=' [%(levelname)-7s] (%(asctime)s) %(filename)s::%(lineno)d %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')


parser = argparse.ArgumentParser()
parser.add_argument("repository_paths", nargs='*',
                    help="The path to the directory containing the repository to process")
parser.add_argument("-o", "--output", default="tasks.repoinfo",
                    help="The path to the repoinfo file to write")
parser.add_argument("--debug", action="store_true",
                    help="Set log level to debug")
parser.add_argument("--info", action="store_true",
                    help="Set log level to info")
parser.add_argument("--test", action="store_true",
                    help="Run tests")


def assemble_repoinfo(path):
    """ Get the information needed to re-link issues and commits from a todo file.
    >>> assemble_repoinfo(".")
    {'commit_uri_prefix': 'https://github.com/DisyInformationssysteme/git-to-jira-links/commit/'}
    """
    R = dulwich.repo.Repo(path)
    C = R.get_config()
    commit_uri_prefix = C.get((b"remote", b"origin"), b"url")
    # turn the commit_uri_prefix into a link
    commit_uri_prefix = commit_uri_prefix[commit_uri_prefix.index(b"//")+2:]
    if b"@" in commit_uri_prefix:
        commit_uri_prefix = commit_uri_prefix[commit_uri_prefix.index(b"@") + 1:]
    commit_uri_prefix = b"https://" + commit_uri_prefix + b"/commit/"
    return {'commit_uri_prefix': commit_uri_prefix.decode("utf-8")}
    

def write_repoinfo(info, filepath):
    """ Store the repoinfo in the given file.
    
    >>> target = "test_repoinfo.json"
    >>> write_repoinfo(assemble_repoinfo("."), target)
    >>> with open(target) as f: f.read().strip()
    '{"commit_uri_prefix": "https://github.com/DisyInformationssysteme/git-to-jira-links/commit/"}'
    """
    with open(filepath, "w") as f:
        json.dump(info, f)
        

def main(args):
    info = assemble_repoinfo(args.repository_paths[0])
    if args.output:
        write_repoinfo(info, args.output)
    else:
        print(json.dumps(info))


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
