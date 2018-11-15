#!/usr/bin/env python3

"""Link commits from a todo file to jira issues.
"""

import argparse
import subprocess as sp
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
import gpg
import dulwich.repo
import jira
logging.basicConfig(level=logging.WARNING,
                    format=' [%(levelname)-7s] (%(asctime)s) %(filename)s::%(lineno)d %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')


parser = argparse.ArgumentParser()
parser.add_argument("todofiles", nargs='*',
                    help="The path to the todo file to process")
basic_options = parser.add_argument_group("basic options")
basic_options.add_argument("-a", "--jira-api-server", default="https://jira.HOST.TLD/",
                    help="The jira API endpoint to use")
basic_options.add_argument("-r", "--repo-info-file", default="tasks.repoinfo",
                    help="The path to the repoinfo file to use")
basic_options.add_argument("-g", "--netrc-gpg-path", default="~/.netrc.gpg",
                    help="The path to a gpg-encrypted netrc file")
# only link the issues if asked to explicitly, because undoing that would be hard.
basic_options.add_argument("-c", "--create-the-links", action="store_true",
                    help="Actually create the links (without this option it only shows what it would do).")
customization = parser.add_argument_group("customization")
customization.add_argument("-l", "--logfile-for-processed-tasks", default="finished_tasks.log",
                    help="Store the processed tasks from the todo files to the given file (appending to the file)")
customization.add_argument("-e", "--exclude-file", default="finished_tasks.log",
                    help="Exclude tasks from the given file, by default the same as the logfile to avoid creating duplicate links.")
customization.add_argument("-t", "--icon-url", default="https://jira.HOST.TLD/gitlab-logo-square-16x16.png",
                    help="The URL to the icon image for issues")
misc = parser.add_argument_group("misc")
misc.add_argument("-u", "--jira-username",
                    help="The username to use for modifying jira issues when not using the netrc.gpg")
misc.add_argument("-p", "--jira-password",
                    help="The password to use for modifying jira issues when not using the netrc.gpg")
misc.add_argument("--debug", action="store_true",
                    help="Set log level to debug")
misc.add_argument("--info", action="store_true",
                    help="Set log level to info")
misc.add_argument("--error", action="store_true",
                    help="Set log level to error")
misc.add_argument("--test", action="store_true",
                    help="Run tests")


def read_todo(filepath):
    """ Read the todo file
    
    >>> todofile = "testtask.todo"
    >>> list(read_todo(todofile))[:1]
    ['016add7c00f6da53ee3c36b227672b416419c972 TEST-123 2018-11-15 TEST-123 initial commit of public version---\\n']
    """
    with open(filepath) as f:
        for i in f:
            yield i

def login_info_from_netrc(data, machine):
    """Retrieve username and password for the last entry matching the given machine from the netrc file

    :param data: bytes, i.e. b'machine FOO'

    >>> sorted(login_info_from_netrc(b"machine jira.HOST.TLD login USER password PASSWORD\\n", "jira.HOST.TLD").items())
    [('password', 'PASSWORD'), ('user', 'USER')]
    >>> sorted(login_info_from_netrc(b"machine jira.HOST.TLD login USER password PASSWORD\\nmachine jira.HOST.TLD login USER2 password PASSWORD2\\n", "jira.HOST.TLD").items())
    [('password', 'PASSWORD2'), ('user', 'USER2')]
    """
    temp = tempfile.NamedTemporaryFile()
    temp.write(data)
    temp.flush() # ensure that the data is written
    parsed = netrc.netrc(temp.name)
    res = parsed.authenticators(machine)
    temp.close() # the data is gone now
    return {"user": res[0], "password": res[2]}
    

def host_from_jira_server(prefix):
    """
    >>> host_from_jira_server("https://jira.HOST.TLD/rest/api/2/")
    'jira.HOST.TLD'
    >>> host_from_jira_server("https://jira.HOST.TLD")
    'jira.HOST.TLD'
    """
    return prefix.split("://")[1].split("/")[0]

def process_taskline(taskline, commit_uri_prefix):
    """Retrieve issue_id, url, and title from a taskline in a todo file.

    >>> process_taskline('12345 TEST-123 2018-08-12 TEST-123 foo\\n', 'http://git.HOST.TLD/my-project/my-repository/commit/')
    ('TEST-123', 'http://git.HOST.TLD/my-project/my-repository/commit/12345', '2018-08-12 TEST-123 foo')
    """
    commit_id, issue_id, isodate, title = taskline.split(" ", 3)
    shorttitle = title.split('---')[0]
    # if the title is too short, include the second non-empty line
    if len(shorttitle) < 20:
        shorttitle = " - ".join([i for i in title.split('---')
                                 if i.strip()][:2])
    return (issue_id,
            commit_uri_prefix + commit_id, 
            " ".join((isodate, shorttitle.strip())))

def create_a_link(authed_jira, issue_id, url, title, icon_url):
    """Actually create the links."""
    # shorten too long titles
    if title[255:]:
             title = title[:251]+ " ..."
    linkobject = {"url": url, "title": title,
                  "icon": {"url16x16": icon_url,
                           "title": "Gitlab"}}
    # adding a global ID requires admin credentials
    # authed_jira.add_remote_link(issue_id,
    #                             {"url": url, "title": title},
    #                             globalId=issue_id+url)
    links = get_all_links(authed_jira, issue_id)
    if url in links:
        # FIXME: This is almost exactly factor 100 slower than initial creation.
        links[url].update(linkobject)
    else:
        authed_jira.add_simple_link(issue_id, linkobject)
        
@functools.lru_cache(maxsize=60000)
def get_all_links(authed_jira, issue_id):
    """Retrieve all links defined in the issue."""
    links = authed_jira.remote_links(issue_id)
    return {i.object.url: i for i in links}    

    
def main(args):
    if args.jira_username is None or args.jira_password is None:
        netrc_path = os.path.expanduser(args.netrc_gpg_path)
        if not os.path.isfile(netrc_path):
            logging.error("netrc file %s not found", netrc_path)
            sys.exit(1)
        with gpg.Context() as c:
            with open(netrc_path) as f:
                login_info = login_info_from_netrc(c.decrypt(f)[0],
                                                   host_from_jira_server(
                                                       args.jira_api_server))
        user, password = login_info["user"], login_info["password"]
    else:
        user, password = args.jira_username, args.jira_password   

    with open(args.repo_info_file) as f:
        repoinfo = json.load(f)
    commit_uri_prefix = repoinfo["commit_uri_prefix"]

    try:
        excluded = set(read_todo(args.exclude_file))
    except FileNotFoundError as e:
        logging.warn("Exclude file not found: %s", args.exclude_file)
        excluded = set()
    tasklines = []
    for i in args.todofiles:
        tasklines.extend([i for i in read_todo(i)
                          if not i in excluded])

    try:
        authed_jira = jira.JIRA(args.jira_api_server, basic_auth=(user, password))
    except jira.exceptions.JIRAError as e:
        if "CAPTCHA_CHALLENGE" in str(e):
            logging.error(
                ("JIRA requires a CAPTCHA, please log in to %s in the browser to solve them"
                 "(log out first if you are already logged in)."
                 "Please also check that the PASSWORD used is correct."),
                args.jira_api_server)
            def ask(msg, options, default="y"):
                def getletter(msg):
                    return "".join(input(msg).lower().strip()[:1])
                reply = getletter(msg)
                while (reply not in options
                       and not (default and reply == "")):
                    reply = getletter(msg)
                return (reply if reply else default)
            reply = ask("Open jira in browser (Y, n)? ", ["y", "n"], default="y")
            if reply == "y":
                import webbrowser
                webbrowser.open(args.jira_api_server)
            else:
                logging.warn("Not opening browser, please login to %s manually.",
                             args.jira_api_server)
        else:
            raise  
    starttime = time.time()
    with open(args.logfile_for_processed_tasks, "a") as f:
        for taskline in tasklines:
            issue_id, url, title = process_taskline(taskline, commit_uri_prefix)
            try:
                links = get_all_links(authed_jira, issue_id)
            except jira.exceptions.JIRAError as e:
                logging.error(e)
                continue
            if args.create_the_links:
                create_a_link(authed_jira, issue_id, url, title, args.icon_url)
                f.write(taskline)
                logging.info("created link using jira server %s for issue %s using url %s and title %s",
                             args.jira_api_server, issue_id, url, title)
            else:
                logging.warn("Tryout mode! Use -c to create link using jira server %s for issue %s using url %s and title %s",
                             args.jira_api_server, issue_id, url, title)
    if args.create_the_links:
        stoptime = time.time()
        logging.info("created %s links in %s seconds", len(tasklines), stoptime - starttime)
    


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
    if args.error:
        logging.getLogger().setLevel(logging.ERROR)
    if args.test:
        print(_test(args))
    else:
        main(args)
