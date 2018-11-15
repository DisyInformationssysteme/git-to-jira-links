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
basic_options.add_argument("-g", "--netrc-gpg-path", default="~/.netrc.gpg",
                    help="The path to a gpg-encrypted netrc file")
# only link the issues if asked to explicitly, because undoing that would be hard.
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

    all_bugs = authed_jira.search_issues('type=Bug OR type=Sub-bug', fields="key", maxResults=False)
    for issue in all_bugs:
        print (issue.key)
    


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
