import sys
import traceback
import signal
import requests
from requests.auth import HTTPBasicAuth
import json
import urllib3
import urllib.parse

from jira2gitlab_secrets import *
from jira2gitlab_config import *

### set library defaults
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# increase the number of retry connections
requests.adapters.DEFAULT_RETRIES = 10

# close redundant connections
# requests uses the urllib3 library, the default http connection is keep-alive, requests set False to close.
s = requests.session()
s.keep_alive = False

# Jira users that could not be mapped to Gitlab users
jira_users = set()

def project_users(jira_project):
    # Load Jira project issues, with pagination (Jira has a limit on returned items)
    # This assumes they will all fit in memory
    start_at = 0
    jira_issues = []
    while True:
        query = f'{JIRA_API}/search?jql=project="{jira_project}" ORDER BY key&fields=*navigable,attachment,comment,worklog&maxResults={str(JIRA_PAGINATION_SIZE)}&startAt={start_at}'
        try:
            jira_issues_batch = requests.get(
                query,
                auth = HTTPBasicAuth(*JIRA_ACCOUNT),
                verify = VERIFY_SSL_CERTIFICATE,
                headers = {'Content-Type': 'application/json'}
            )
            jira_issues_batch.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Unable to query {query} in Jira!\n{e}")
        jira_issues_batch = jira_issues_batch.json()['issues']
        if not jira_issues_batch:
            break

        start_at = start_at + len(jira_issues_batch)
        jira_issues.extend(jira_issues_batch)
        print(f"\r[INFO] Loading Jira issues from project {jira_project} ... {str(start_at)}", end='', flush=True)
    print("\n")

    # Import issues into Gitlab
    for index, issue in enumerate(jira_issues, start=1):
        print(f"\r[INFO] #{index}/{len(jira_issues)} Looking at Jira issue {issue['key']} ...   ", end='', flush=True)

        # Reporter
        reporter = 'jira' # if no reporter is available, use root
        if 'reporter' in issue['fields'] and 'name' in issue['fields']['reporter']:
            reporter = issue['fields']['reporter']['name']
            jira_users.add(reporter)

        for comment in issue['fields']['comment']['comments']:
            author = comment['author']['name']
            jira_users.add(author)

    print("\n")
    print(*list(dict.fromkeys(sorted(jira_users))), sep = "\n")

for jira_project, gitlab_project in PROJECTS.items():
    print(f"\n\nGet participants of {jira_project}")
    project_users(jira_project)
