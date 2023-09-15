#!/usr/bin/python

# Improved upon https://gist.github.com/Gwerlas/980141404bccfa0b0c1d49f580c2d494

# Jira API documentation : https://docs.atlassian.com/software/jira/docs/api/REST/8.5.1/
# Gitlab API documentation: https://docs.gitlab.com/ee/api/README.html

import re
import sys
import uuid
import json
import signal
import pickle
import hashlib
import urllib3
import requests
import traceback
import unicodedata
import urllib.parse

from io import BytesIO
from pathlib import Path
from typing import Dict, Any
from requests.auth import HTTPBasicAuth
from requests import adapters as req_adapters

from jira2gitlab_config import *
from jira2gitlab_secrets import *
from label_colors import create_or_update_label_colors

IMPORT_STATUS_FILENAME = "import_status.pickle"

########################
# Set library defaults #
########################

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Increase the number of retry connections
req_adapters.DEFAULT_RETRIES = 10

# Close redundant connections
# Requests uses the urllib3 library, the default http connection is keep-alive, requests set False to close.
session_settings = requests.session()
session_settings.keep_alive = False


# Translate types that the json module cannot encode
def json_encoder(obj):
    if isinstance(obj, set):
        return list(obj)


# Hash a dictionary
def dict_hash(dictionary: Dict[str, Any]) -> str:
    dhash = hashlib.md5()
    encoded = json.dumps(dictionary, sort_keys=True).encode()
    dhash.update(encoded)
    return dhash.hexdigest()


# Remove unstable data from a Jira issue
# Unstable data is data that changes even though the issue has not been changed
def jira_issue_remove_unstable_data(issue: dict):
    for field in ("lastViewed", "customfield_10300"):
        if field in issue["fields"]:
            issue["fields"][field] = ""


# Convert Jira tables to markdown
def jira_table_to_markdown(text):
    """ Convert jira tables in issues to tables in markdown """
    lines: list = text.splitlines()
    lines_len = len(lines)
    i = 0

    # Turn in-cell newlines into <br> and re-concatenate mistakenly broken rows
    while i < lines_len:
        j = 0
        if lines[i] and lines[i][0] == "|":
            while i + j < lines_len - 1 and lines[i][-1] != "|":
                j = j + 1
                lines[i] = lines[i] + "<br>" + lines[i + j]

            if i + j == lines_len - 1:
                # End is reached without finding a closing "|" -> something is wrong
                if not FORCE_REPAIR_JIRA_TABLES:  # Abort if force_repair is False
                    return text

            for k in range(j):
                lines[i + 1 + k] = None

        i = i + j + 1

    lines = list(filter(None, lines))
    found_table = False

    # Change the ||-delimited header in to |-delimited
    # and insert | --- | separator line
    for i in range(len(lines)):
        if lines[i] and lines[i][:2] == "||" and lines[i][-2:] == "||":
            found_table = True
            pp = 0  # pee-pee haha
            p = 0
            for c in lines[i]:
                if c == "|":
                    p += 1
                    if p == 2:
                        pp += 1
                        p = 0
            sep = "\n" + "| --- " * (pp - 1) + "|"
            lines[i] = re.sub(r"\|\|", r"|", lines[i]) + sep

    # Try force repairing the broken table
    if FORCE_REPAIR_JIRA_TABLES and not found_table:
        pp = 0
        found_broken_table = False
        for i in range(lines_len):
            if lines[i] and lines[i][:1] == "|" and lines[i][-1:] == "|":
                found_broken_table = True
                pp = 0
                p = 0
                for c in lines[i]:
                    if c == "|":
                        p += 1
                        if p == 2:
                            pp += 1
                            p = 0
                break

        if found_broken_table:
            sep = "\n" + "| --- " * (pp * 2 - 1) + "|"
            lines[i] = re.sub(r"\|\|", r"|", lines[i]) + sep

    return "\n".join(lines)


# Gitlab markdown : https://docs.gitlab.com/ee/user/markdown.html
# Jira text formatting notation : https://jira.atlassian.com/secure/WikiRendererHelpAction.jspa?section=all
def jira_text_2_gitlab_markdown(jira_project, text, adict):
    if text is None:
        return ""

    t = text
    # Tables
    t = jira_table_to_markdown(t)

    # Sections and links
    t = re.sub(r'(\r?\n)', r'  \1', t)  # line breaks
    t = re.sub(r'\{code}\s*', r'\n```\n', t)  # Block code (simple)
    t = re.sub(r'\{code:(\w+)(?:\|\w+=[\w.\-]+)*}\s*', r'\n```\1\n', t)  # Block code (with language and properties)
    t = re.sub(r'\{code:[^}]*}\s*', r'\n```\n', t)  # Block code (catch-all, bailout to simple)
    t = re.sub(r'\n\s*bq\. (.*)\n', r'\n> \1\n', t)  # Block quote
    t = re.sub(r'\{quote}', r'\n>>>\n', t)  # Block quote #2
    t = re.sub(r'\{color:[#\w]+}(.*)\{color}', r'> **\1**', t)  # Colors
    t = re.sub(r'\n-{4,}\n', r'---', t)  # Ruler
    t = re.sub(r'\[~([a-z]+)]', r'@\1', t)  # Links to users
    t = re.sub(r'\[([^|\]]*)]', r'\1', t)  # Links without alt
    t = re.sub(r'\[(.+)\|([a-z]+://.+)]', r'[\1](\2)', t)  # Links with alt
    t = re.sub(r'(\b%s-\d+\b)' % jira_project, r'[\1](%s/browse/\1)' % JIRA_URL, t)  # Links to other issues
    # Lists
    t = re.sub(r'\n *# ', r'\n 1. ', t)  # Ordered list
    t = re.sub(r'\n *[*\-#]# ', r'\n   1. ', t)  # Ordered sub-list
    t = re.sub(r'\n *[*\-#]{2}# ', r'\n     1. ', t)  # Ordered sub-sub-list
    t = re.sub(r'\n *\* ', r'\n - ', t)  # Unordered list
    t = re.sub(r'\n *[*\-#][*\-] ', r'\n   - ', t)  # Unordered sub-list
    t = re.sub(r'\n *[*\-#]{2}[*\-] ', r'\n     - ', t)  # Unordered sub-sub-list
    # Text effects
    t = re.sub(r'(^|\W)\*(\S.*\S)\*(\W|$)', r'\1**\2**\3', t)  # Bold
    t = re.sub(r'(^|\W)_(\S.*\S)_(\W|$)', r'\1*\2*\3', t)  # Emphasis
    t = re.sub(r'(^|\W)-([^\s\-|].*[^\s\-|])-(\W|$)', r'\1~~\2~~\3', t)  # Deleted / Strikethrough
    t = re.sub(r'(^|\W)\+(\S.*\S)\+(\W|$)', r'\1__\2__\3', t)  # Underline
    t = re.sub(r'(^|\W)\{\{([^}]*)}}(\W|$)', r'\1`\2`\3', t)  # Inline code
    # Titles
    t = re.sub(r'\n?\bh1\. ', r'\n# ', t)
    t = re.sub(r'\n?\bh2\. ', r'\n## ', t)
    t = re.sub(r'\n?\bh3\. ', r'\n### ', t)
    t = re.sub(r'\n?\bh4\. ', r'\n#### ', t)
    t = re.sub(r'\n?\bh5\. ', r'\n##### ', t)
    t = re.sub(r'\n?\bh6\. ', r'\n###### ', t)
    # Emojis : https://emoji.codes
    t = re.sub(r':\)', r':smiley:', t)
    t = re.sub(r':\(', r':disappointed:', t)
    t = re.sub(r':P', r':yum:', t)
    t = re.sub(r':D', r':grin:', t)
    t = re.sub(r';\)', r':wink:', t)
    t = re.sub(r'\(y\)', r':thumbsup:', t)
    t = re.sub(r'\(n\)', r':thumbsdown:', t)
    t = re.sub(r'\(i\)', r':information_source:', t)
    t = re.sub(r'\(/\)', r':white_check_mark:', t)
    t = re.sub(r'\(x\)', r':x:', t)
    t = re.sub(r'\(!\)', r':warning:', t)
    t = re.sub(r'\(\+\)', r':heavy_plus_sign:', t)
    t = re.sub(r'\(-\)', r':heavy_minus_sign:', t)
    t = re.sub(r'\(\?\)', r':grey_question:', t)
    t = re.sub(r'\(on\)', r':bulb:', t)
    # t = re.sub(r'\(off\)', r':', t) # Not found
    t = re.sub(r'\(\*[rgby]?\)', r':star:', t)

    # Process custom substitutions
    for k, v in adict.items():
        t = re.sub(k, v, t)

    return t


# Migrate a list of attachments
# We use UUID in place of the filename to prevent 500 errors on unicode chars
# The attachments need to be explicitly mentioned to be visible in Gitlab issues
def move_attachments(attachments, gitlab_project_id):
    replacements = {}
    for attachment in attachments:
        author = "jira"  # if user is not valid, use root
        if "author" in attachment:
            author = attachment["author"]["name"]

        clean_filename = ""
        if KEEP_ORIGINAL_ATTACHMENT_FILENAMES:
            filename = attachment["filename"]
            # Try to clean up some unicode characters by stripping accents
            n_chars = (c for c in unicodedata.normalize("NFD", filename) if unicodedata.category(c) != "Mn")
            clean_filename = "".join(n_chars)

        _file = requests.get(
            attachment["content"],
            auth=HTTPBasicAuth(*JIRA_ACCOUNT),
            verify=VERIFY_SSL_CERTIFICATE,
        )

        if not _file:
            print(f"[WARN] Unable to migrate attachment: {attachment['content']} ... ")
            continue

        _content = BytesIO(_file.content)

        file_data = (clean_filename, _content) if KEEP_ORIGINAL_ATTACHMENT_FILENAMES \
            else (str(uuid.uuid4()), _content)  # Some random string as file name

        file_info = requests.post(
            f"{GITLAB_API}/projects/{gitlab_project_id}/uploads",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Sudo": resolve_login(author)["username"]},
            files={"file": file_data},
            verify=VERIFY_SSL_CERTIFICATE
        )

        del _content

        if not file_info:
            print(f"[WARN] Unable to migrate attachment: {attachment['content']} ... ")
            continue

        file_info = file_info.json()

        # Add this to replacements for comments mentioning these attachments
        key = rf"!{re.escape(attachment['filename'])}[^!]*!"
        # value = rf"![{attachment['filename']}]({file_info['url']})"

        # Changed url for the attachments to a full path to avoid problems for epics/issues
        full_file_path = f"{GITLAB_URL}{file_info['full_path']}"
        value = rf"![{attachment['filename']}]({full_file_path})"

        replacements[key] = value

    return replacements


# Get the ID of a Gitlab milestone name
def get_milestone_id(gl_milestones, gitlab_project_id, title):
    for milestone in gl_milestones:
        if milestone["title"] == title:
            return milestone["id"]

    # Milestone not found in local cache, check in Gitlab
    try:
        milestones = requests.get(
            f"{GITLAB_API}/projects/{gitlab_project_id}/milestones?title={title}",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE
        )
        milestones.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to search milestone {title} in Gitlab\n{e}")

    milestones = milestones.json()

    if milestones:
        # Found in Gitlab
        milestone = milestones[0]
    else:
        # Milestone doesn't exist in Gitlab, we create it
        milestone = requests.post(
            f"{GITLAB_API}/projects/{gitlab_project_id}/milestones",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE,
            json={"title": title}
        )
        if not milestone:
            raise Exception(f"Could not add milestone {title} in Gitlab")

        milestone = milestone.json()

    gl_milestones.append(milestone)
    return milestone["id"]


# Change admin role of Gitlab users
def gitlab_user_admin(user, admin):
    # Cannot change root's admin status
    if user["username"] == GITLAB_ADMIN:
        return user

    try:
        gl_user = requests.put(
            f"{GITLAB_API}/users/{user['id']}",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE,
            json={"admin": admin}
        )
        gl_user.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable change admin status of Gitlab user {user['username']} to {admin}\n{e}")

    gl_user = gl_user.json()

    if admin:
        IMPORT_STATUS["gl_users_made_admin"].add(gl_user["username"])
    else:
        IMPORT_STATUS["gl_users_made_admin"].remove(gl_user["username"])

    return gl_user


# Find or create the Gitlab user corresponding to the given Jira user
def resolve_login(jira_username):
    if jira_username == "jira":
        return gl_users[GITLAB_ADMIN]

    # Mapping found
    if jira_username in USER_MAP:
        gl_username = USER_MAP[jira_username]

        # User exists in Gitlab
        if gl_username in gl_users:
            gl_user = gl_users[gl_username]
            if MAKE_USERS_TEMPORARILY_ADMINS and not gl_users[gl_username]["is_admin"]:
                gl_user = gitlab_user_admin(gl_users[gl_username], True)
            return gl_user

        # User doesn't exist in Gitlab, migrate it if allowed
        if MIGRATE_USERS:
            return migrate_user(jira_username)

        # Not allowed to migrate the user, log it
        if gl_username in gl_users_not_migrated:
            gl_users_not_migrated[gl_username] += 1
        else:
            gl_users_not_migrated[gl_username] = 1

        return gl_users[GITLAB_ADMIN]

    # No mapping found, log jira user
    if jira_username in jira_users_not_mapped:
        jira_users_not_mapped[jira_username] += 1
    else:
        jira_users_not_mapped[jira_username] = 1

    return gl_users[GITLAB_ADMIN]


# Migrate a user
def migrate_user(jira_username):
    print(f"\n[INFO] Migrating user {jira_username}")

    if jira_username == "jira":
        return gl_users[GITLAB_ADMIN]

    try:
        jira_user = requests.get(
            f"{JIRA_API}/user?username={jira_username}",
            auth=HTTPBasicAuth(*JIRA_ACCOUNT),
            verify=VERIFY_SSL_CERTIFICATE,
            headers={"Content-Type": "application/json"}
        )
        jira_user.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to read {jira_username} from Jira!\n{e}")

    jira_user = jira_user.json()

    try:
        gl_user = requests.post(
            f"{GITLAB_API}/users",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE,
            json={
                "admin": MAKE_USERS_TEMPORARILY_ADMINS,
                "email": jira_user["emailAddress"],
                "username": jira_username,
                "name": jira_user["displayName"],
                "password": NEW_GITLAB_USERS_PASSWORD
            }
        )
        gl_user.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to create {jira_username} in Gitlab!\n{e}")

    gl_user = gl_user.json()

    if MAKE_USERS_TEMPORARILY_ADMINS:
        IMPORT_STATUS["gl_users_made_admin"].add(gl_user["username"])

    gl_users[gl_user["username"]] = gl_user

    return gl_user


# Create Gitlab project
def create_gl_project(gitlab_project):
    print(f"\n[INFO] Creating Gitlab project {gitlab_project}")

    [namespace, project] = gitlab_project.rsplit("/", 1)
    if namespace in gl_namespaces:
        namespace_id = gl_namespaces[namespace]["id"]
    else:
        raise Exception(f"Could not find namespace {namespace} in Gitlab!")

    try:
        gl_project = requests.post(
            f"{GITLAB_API}/projects",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE,
            json={
                "path": project,
                "namespace_id": namespace_id,
                "visibility": "internal",
            }
        )
        gl_project.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to create {gitlab_project} in Gitlab!\n{e}")

    return gl_project.json()["id"]


# Migrate a project
def migrate_project(jira_project, gitlab_project):
    jira_gl_epic_issues_map = {}  # Dict with the structure of: <JIRA_ISSUE_KEY>: <GITLAB_EPIC_ID>
    gitlab_group_id = None

    if GITLAB_PREMIUM:  # Prerequisites to be able to create epics (premium only)
        # Get the group ID of the project - used for creating epic issues
        group_path = "/".join(gitlab_project.rstrip("/").split("/")[:-1])
        if not group_path:
            raise ValueError("Incorrect definition of `path/to/group/project` for gitlab")

        try:
            group_data_resp = requests.get(
                f"{GITLAB_API}/groups?search={group_path}",
                headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
                verify=VERIFY_SSL_CERTIFICATE
            )
            group_data_resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Unable to get group id for {gitlab_project}!\n{e}")

        groups_data = group_data_resp.json()
        if not groups_data:
            raise ValueError("Did not find any groups matching the given path for the gitlab project!")

        for group_data in groups_data:
            if group_data["full_path"] == group_path:
                gitlab_group_id = group_data["id"]

    # Get the project ID, create it if necessary.
    try:
        project = requests.get(
            f"{GITLAB_API}/projects/{urllib.parse.quote(gitlab_project, safe='')}",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE
        )
        project.raise_for_status()
        gitlab_project_id = project.json()["id"]
    except requests.exceptions.RequestException:
        gitlab_project_id = create_gl_project(gitlab_project)

    # Load the Gitlab project's milestone list (empty for a new import)
    try:
        gl_milestones = requests.get(
            f"{GITLAB_API}/projects/{gitlab_project_id}/milestones",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE
        )
        gl_milestones.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to list Gitlab milestones for project {gitlab_project}!\n{e}")

    gl_milestones = gl_milestones.json()

    # Load Jira project issues, with pagination (Jira has a limit on returned items)
    # This assumes they will all fit in memory
    start_at = 0
    jira_issues = []
    while True:
        query = (f'{JIRA_API}/search?jql=project="{jira_project}" '
                 f'ORDER BY key&fields=*navigable,attachment,comment,'
                 f'worklog&maxResults={str(JIRA_PAGINATION_SIZE)}&startAt={start_at}')
        try:
            jira_issues_batch = requests.get(
                query,
                auth=HTTPBasicAuth(*JIRA_ACCOUNT),
                verify=VERIFY_SSL_CERTIFICATE,
                headers={"Content-Type": "application/json"}
            )
            jira_issues_batch.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Unable to query {query} in Jira!\n{e}")

        jira_issues_batch = jira_issues_batch.json()["issues"]
        if not jira_issues_batch:
            break

        start_at = start_at + len(jira_issues_batch)
        jira_issues.extend(jira_issues_batch)
        print(f"\r[INFO] Loading Jira issues from project {jira_project} ... {str(start_at)}", end="", flush=True)

    print("\n")

    # Put epics at the top of the list of jira issues as they need to be created first in gitlab (premium only)
    if GITLAB_PREMIUM:
        epics = []
        the_rest = []
        for issue in jira_issues:
            if issue["fields"]["issuetype"]["name"] == "Epic":
                epics.append(issue)
            else:
                the_rest.append(issue)

        jira_issues = epics + the_rest

    # Import issues into Gitlab
    for index, issue in enumerate(jira_issues, start=1):
        jira_issue_remove_unstable_data(issue)
        issue_hash = dict_hash(issue)
        weight = None
        replacements = dict()

        # Skip issues that were already imported and have not changed
        if issue["key"] in IMPORT_STATUS["issue_mapping"]:
            if IMPORT_STATUS["issue_mapping"][issue["key"]][1] == issue_hash:
                print(f"[INFO] Issue {issue['key']} found in status with the same hash: "
                      f"previously imported and not changed.", flush=True)
                continue
            else:
                print(f"[INFO] #{index}/{len(jira_issues)} Jira issue {issue['key']} was imported before, "
                      f"but it has changed. Deleting and re-importing.", flush=True)

                # Define url based on the issue being an epic or not
                issue_url = (f"{GITLAB_API}/projects/{gitlab_project_id}/issues/"
                             f"{IMPORT_STATUS['issue_mapping'][issue['key']][0]['iid']}")
                if GITLAB_PREMIUM and issue["fields"]["issuetype"]["name"] == "Epic":
                    issue_url = (f"{GITLAB_API}/groups/{gitlab_group_id}/epics/"
                                 f"{IMPORT_STATUS['issue_mapping'][issue['key']][0]['id']}")

                requests.delete(
                    url=issue_url,
                    headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
                    verify=VERIFY_SSL_CERTIFICATE,
                )
        else:
            print(f"\r[INFO] #{index}/{len(jira_issues)} Migrating Jira issue {issue['key']} ...   ",
                  end="", flush=True)

        # Reporter
        reporter = "jira"  # if no reporter is available, use root
        if "reporter" in issue["fields"] and issue["fields"]["reporter"] and "name" in issue["fields"]["reporter"]:
            reporter = issue["fields"]["reporter"]["name"]

        # Assignee (can be empty)
        gl_assignee = None
        if issue["fields"]["assignee"]:
            gl_assignee = [resolve_login(issue["fields"]["assignee"]["name"])["id"]]

        # Mark all issues as imported
        gl_labels = ["jira-import"]

        # Migrate existing labels
        if "labels" in issue["fields"]:
            gl_labels.extend([PREFIX_LABEL + sub for sub in issue["fields"]["labels"]])

        # Issue type to label
        if issue["fields"]["issuetype"]["name"] in ISSUE_TYPE_MAP:
            gl_labels.append(ISSUE_TYPE_MAP[issue["fields"]["issuetype"]["name"]])
        else:
            print(f"\n[WARN] Jira issue type {issue['fields']['issuetype']['name']} not mapped."
                  f" Importing as generic label.", flush=True)
            gl_labels.append(issue["fields"]["issuetype"]["name"].lower())

        # Priority to label
        if "priority" in issue["fields"]:
            if issue["fields"]["priority"] and issue["fields"]["priority"]["name"] in ISSUE_PRIORITY_MAP:
                gl_labels.append(ISSUE_PRIORITY_MAP[issue["fields"]["priority"]["name"]])
            else:
                gl_labels.append(PREFIX_PRIORITY + issue["fields"]["priority"]["name"].lower())

        # Issue components to labels
        for component in issue["fields"]["components"]:
            if component["name"] in ISSUE_COMPONENT_MAP:
                gl_labels.append(ISSUE_COMPONENT_MAP[component["name"]])
            else:
                gl_labels.append(PREFIX_COMPONENT + component["name"].lower())

        # Issue status to label
        if issue["fields"]["status"] and issue["fields"]["status"]["name"] in ISSUE_STATUS_MAP:
            gl_labels.append(ISSUE_STATUS_MAP[issue["fields"]["status"]["name"]])

        # Resolution is also mapped into a status
        if issue["fields"]["resolution"] and issue["fields"]["resolution"]["name"] in ISSUE_RESOLUTION_MAP:
            gl_labels.append(ISSUE_RESOLUTION_MAP[issue["fields"]["resolution"]["name"]])

        # Storypoints / weight
        if JIRA_STORY_POINTS_FIELD in issue["fields"] and issue["fields"][JIRA_STORY_POINTS_FIELD]:
            weight = int(issue["fields"][JIRA_STORY_POINTS_FIELD])

        # Epic name to label
        if not GITLAB_PREMIUM and (JIRA_EPIC_FIELD in issue["fields"] and issue["fields"][JIRA_EPIC_FIELD]):
            epic_info = requests.get(
                f"{JIRA_API}/issue/{issue['fields'][JIRA_EPIC_FIELD]['id']}/?fields=summary",
                auth=HTTPBasicAuth(*JIRA_ACCOUNT),
                verify=VERIFY_SSL_CERTIFICATE,
                headers={"Content-Type": "application/json"}
            ).json()
            gl_labels.append(epic_info["fields"]["summary"])

        # Last fix versions to milestone
        gl_milestone_id = None
        for fixVersion in issue["fields"]["fixVersions"]:
            gl_milestone_id = get_milestone_id(gl_milestones, gitlab_project_id, fixVersion['name'])

        # Collect issue links, to be processed after all Gitlab issues are created
        # Only "outward" links were collected.
        # I.e. we only need to process (a blocks b), as (b blocked by a) comes implicitly.
        for link in issue["fields"]["issuelinks"]:
            if "outwardIssue" in link:
                IMPORT_STATUS["links_todo"].add((issue["key"], link["type"]["outward"], link["outwardIssue"]["key"]))

        # There is no sub-task equivalent in Gitlab
        # Use a (sub-task, blocks, task) link instead
        for subtask in issue["fields"]["subtasks"]:
            IMPORT_STATUS["links_todo"].add((subtask["key"], "blocks", issue["key"]))

        # Migrate attachments and get replacements for comments pointing at them
        if MIGRATE_ATTACHMENTS:
            replacements = move_attachments(issue["fields"]["attachment"], gitlab_project_id)

        # Create Gitlab issue
        # Add a link to the Jira issue and mention all attachments in the description
        gl_description = jira_text_2_gitlab_markdown(jira_project, issue["fields"]["description"], replacements)
        gl_description += "\n\n___\n\n"
        gl_description += f"**Imported from Jira issue [{issue['key']}]({JIRA_URL}/browse/{issue['key']})**\n\n"

        gl_reporter = resolve_login(reporter)["username"]
        if gl_reporter == GITLAB_ADMIN and reporter != "jira":
            gl_description += f"**Original creator of the issue: Jira user {reporter}**\n\n"

        if MIGRATE_ATTACHMENTS:
            for attachment in replacements.values():
                if attachment not in gl_description:
                    gl_description += (f"Attachment imported from Jira issue "
                                       f"[{issue['key']}]({JIRA_URL}/browse/{issue['key']}): {attachment}\n\n")

        try:
            gl_title = ""
            if ADD_JIRA_KEY_TO_TITLE:
                gl_title = f"[{issue['key']}] "
            gl_title += f"{issue['fields']['summary']}"
            original_title = ""

            if len(gl_title) > 255:
                # add full original title as a comment later on
                original_title = f"Full original title:\n\n{gl_title}\n\n"
                gl_title = gl_title[:252] + "..."

            data = {
                "created_at": issue["fields"]["created"],
                "assignee_ids": gl_assignee,
                "title": gl_title,
                "description": original_title + gl_description,
                "milestone_id": gl_milestone_id,
                "labels": ", ".join(gl_labels),
            }
            if weight is not None:
                data["weight"] = weight

            if GITLAB_PREMIUM and issue["fields"]["issuetype"]["name"] == "Epic":
                # Create the epic on the group
                gl_issue = requests.post(
                    f"{GITLAB_API}/groups/{gitlab_group_id}/epics",
                    headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Sudo": gl_reporter},
                    verify=VERIFY_SSL_CERTIFICATE,
                    json=data
                )
            else:
                gl_issue = requests.post(
                    f"{GITLAB_API}/projects/{gitlab_project_id}/issues",
                    headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Sudo": gl_reporter},
                    verify=VERIFY_SSL_CERTIFICATE,
                    json=data
                )
            gl_issue.raise_for_status()
        except requests.exceptions.RequestException as e:
            # noinspection PyUnboundLocalVariable
            print(f"data: {data} ... ")
            raise Exception(f"Unable to create Gitlab issue for Jira issue {issue['key']}\n{e}")

        gl_issue = gl_issue.json()

        if GITLAB_PREMIUM and issue["fields"]["issuetype"]["name"] == "Epic":
            jira_gl_epic_issues_map[issue["key"]] = gl_issue["iid"]

        # Collect Jira-Gitlab ID mapping and Jira issue hash
        # to be used later for links and for incremental imports
        IMPORT_STATUS["issue_mapping"][issue["key"]] = (
            {
                "id": gl_issue["id"],
                "project_id": gl_issue["project_id"],
                "iid": gl_issue["iid"],
                "full_ref": gl_issue["references"]["full"]
            },
            issue_hash
        )

        # The Gitlab issue is created, now we add more information
        # If anything after this point fails, we remove the issue to avoid half-imported issues
        try:
            # Assign issue to epic (premium only)
            if GITLAB_PREMIUM and (JIRA_EPIC_FIELD in issue["fields"] and issue["fields"][JIRA_EPIC_FIELD]):
                try:
                    gl_epic_id = jira_gl_epic_issues_map[issue["fields"][JIRA_EPIC_FIELD]]
                    requests.post(
                        url=f"{GITLAB_API}/groups/{gitlab_group_id}/epics/{gl_epic_id}/issues/{gl_issue['id']}",
                        headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Sudo": gl_reporter},
                        verify=VERIFY_SSL_CERTIFICATE
                    )
                except KeyError:
                    print(f"Jira issue `{issue['key']}` is assigned to an epic from another jira project: "
                          f"{issue['fields'][JIRA_EPIC_FIELD]}")

            # Add original comments
            # Define url based on the issue being an epic or not
            notes_add_url = f"{GITLAB_API}/projects/{gitlab_project_id}/issues/{gl_issue['iid']}/notes"
            if GITLAB_PREMIUM and issue["fields"]["issuetype"]["name"] == "Epic":
                notes_add_url = f"{GITLAB_API}/groups/{gitlab_group_id}/epics/{gl_issue['id']}/notes"

            for comment in issue["fields"]["comment"]["comments"]:
                author = comment["author"]["name"]
                gl_author = resolve_login(author)["username"]
                notice = ""
                if gl_author == GITLAB_ADMIN and author != "jira":
                    notice = f"[ Original comment made by Jira user {author} ]\n\n"

                note_add = requests.post(
                    url=notes_add_url,
                    headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Sudo": gl_author},
                    verify=VERIFY_SSL_CERTIFICATE,
                    json={
                        "created_at": comment["created"],
                        "body": notice + jira_text_2_gitlab_markdown(jira_project, comment["body"], replacements)
                    }
                )
                note_add.raise_for_status()

            # Migrate custom fields
            custom_fields_comment = ""
            for key, desc in JIRA_CUSTOM_FIELDS.items():
                if issue["fields"][key]:
                    field_value = str(issue["fields"][key]).replace("\n", "<br>")
                    custom_fields_comment += f"| {desc} | {field_value} |\n"

            if custom_fields_comment:
                table_header = "| Additional metadata | Content |\n"
                table_header += "| - | - |\n"
                gl_author = GITLAB_ADMIN
                note_add = requests.post(
                    url=notes_add_url,
                    headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Sudo": gl_author},
                    verify=VERIFY_SSL_CERTIFICATE,
                    json={"body": table_header + custom_fields_comment}
                )
                note_add.raise_for_status()

            # Add worklogs
            if MIGRATE_WORLOGS:
                for worklog in issue["fields"]["worklog"]["worklogs"]:
                    # not all worklogs have a comment
                    worklog_comment = ""
                    if "comment" in worklog:
                        worklog_comment = jira_text_2_gitlab_markdown(jira_project, worklog["comment"], replacements)
                    author = worklog["author"]["name"]
                    gl_author = resolve_login(author)["username"]
                    if gl_author == GITLAB_ADMIN and author != "jira":
                        body = f"[ Worklog {worklog['timeSpent']} (Original worklog by Jira user {author}) ]\n\n"
                    else:
                        body = f"[ Worklog {worklog['timeSpent']} ]\n\n"
                    body += worklog_comment
                    body += f"\n/spend {worklog['timeSpent']} {worklog['started'][:10]}"
                    note_add = requests.post(
                        url=notes_add_url,
                        headers={"PRIVATE-TOKEN": GITLAB_TOKEN, "Sudo": gl_author},
                        verify=VERIFY_SSL_CERTIFICATE,
                        json={"created_at": worklog["started"], "body": body}
                    )
                    note_add.raise_for_status()

            # Add comments to reference BitBucket commits
            # Only the references to repos mapped in PROJECTS_BITBUCKET are added
            # Note: this an internal call, it is not part of the public API.
            # (https://jira.atlassian.com/browse/JSWCLOUD-16901)
            if REFERECE_BITBUCKET_COMMITS:
                devel_info = requests.get(
                    f"{JIRA_URL}/rest/dev-status/latest/issue/detail"
                    f"?issueId={issue['id']}&applicationType=stash&dataType=repository",
                    auth=HTTPBasicAuth(*JIRA_ACCOUNT),
                    verify=VERIFY_SSL_CERTIFICATE,
                    headers={"Content-Type": "application/json"},
                    timeout=60  # I've seen this call hang indefinitely. Use a timeout to prevent that.
                )
                devel_info.raise_for_status()
                devel_info = devel_info.json()

                for detail in devel_info["detail"]:
                    for repository in detail["repositories"]:
                        for commit in repository["commits"]:
                            match = re.match(BITBUCKET_COMMIT_PATTERN, commit["url"])
                            if match is None:
                                continue
                            bitbucket_ref = f"{match.group(1)}/{match.group(2)}"
                            if bitbucket_ref not in PROJECTS_BITBUCKET:
                                continue
                            commit_reference = (f"[{commit['displayId']} in {bitbucket_ref}]({GITLAB_URL}/"
                                                f"{PROJECTS_BITBUCKET[bitbucket_ref]}/-/commit/{commit['id']})")
                            body = f"{commit['author']['name']} commited {commit_reference} : {commit['message']}"
                            note_add = requests.post(
                                url=notes_add_url,
                                headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
                                verify=VERIFY_SSL_CERTIFICATE,
                                json={"created_at": commit["authorTimestamp"], "body": body}
                            )
                            note_add.raise_for_status()

            # Define url based on the issue being an epic or not
            issue_url = f"{GITLAB_API}/projects/{gitlab_project_id}/issues/{gl_issue['iid']}"
            if GITLAB_PREMIUM and issue["fields"]["issuetype"]["name"] == "Epic":
                issue_url = f"{GITLAB_API}/groups/{gitlab_group_id}/epics/{gl_issue['id']}"

            # Close "done" issues
            # Status-category can only be "new" (To Do) / "indeterminate" (In Progress) /
            # "done" (Done) / "undefined" (Undefined)
            if (issue["fields"]["status"]["statusCategory"]["key"] == "done" or
                    issue["fields"]["status"]["name"] in ISSUE_STATUS_CLOSED):
                data = {"state_event": "close"}
                if issue["fields"]["resolutiondate"]:
                    data["updated_at"] = issue["fields"]["resolutiondate"]
                status = requests.put(
                    url=issue_url,
                    headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
                    verify=VERIFY_SSL_CERTIFICATE,
                    json=data
                )
                status.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"{e}\n")

            # Define url based on the issue being an epic or not
            issue_url = f"{GITLAB_API}/projects/{gitlab_project_id}/issues/{gl_issue['iid']}"
            if GITLAB_PREMIUM and issue["fields"]["issuetype"]["name"] == "Epic":
                issue_url = f"{GITLAB_API}/groups/{gitlab_group_id}/epics/{gl_issue['id']}"

            requests.delete(
                url=issue_url,
                headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
                verify=VERIFY_SSL_CERTIFICATE,
            )

            raise Exception(f"Unable to modify Gitlab issue {gl_issue['id']}. Removing issue and aborting.\n{e}")

        # Issue successfully imported.
        # Write current status to file
        store_import_status()


def process_links():
    for (j_from, j_type, j_to) in IMPORT_STATUS["links_todo"].copy():
        print(f"\r[Info]: Processing link {j_from} {j_type} {j_to}        ", end="", flush=True)

        if not (j_from in IMPORT_STATUS["issue_mapping"] and j_to in IMPORT_STATUS["issue_mapping"]):
            print(f"\n[WARN]: Skipping {j_from} {j_type} {j_to}, at least one of the Gitlab issues was not imported")
            continue

        gl_from = IMPORT_STATUS["issue_mapping"][j_from][0]
        gl_to = IMPORT_STATUS["issue_mapping"][j_to][0]

        # Only "outward" links were collected.
        # I.e. we only need to process (a blocks b), as (b blocked by a) comes implicitly.
        if j_type in ["relates to", "blocks", "causes"]:
            # Gitlab free only support "relates_to" links
            gl_type = "relates_to"

            if GITLAB_PREMIUM and j_type in ["relates to", "blocks"]:
                gl_type = j_type.replace(" ", "_")

            try:
                gl_link = requests.post(
                    f"{GITLAB_API}/projects/{gl_from['project_id']}/issues/{gl_from['iid']}/links",
                    headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
                    verify=VERIFY_SSL_CERTIFICATE,
                    json={
                        "target_project_id": gl_to["project_id"],
                        "target_issue_iid": gl_to["iid"],
                        "link_type": gl_type,
                    }
                )
                gl_link.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"Unable to create Gitlab issue link: {gl_from} {gl_type} {gl_to}\n{e}")

            IMPORT_STATUS["links_todo"].remove((j_from, j_type, j_to))
        else:
            # These Jira links are treated differently in Gitlab
            if j_type == "duplicates":
                try:
                    note_add = requests.post(
                        f"{GITLAB_API}/projects/{gl_from['project_id']}/issues/{gl_from['iid']}/notes",
                        headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
                        verify=VERIFY_SSL_CERTIFICATE,
                        json={
                            "body": f"/duplicate {gl_to['full_ref']}"
                        }
                    )
                    note_add.raise_for_status()
                except requests.exceptions.RequestException as e:
                    print(f"[WARN] Unable to create Gitlab issue link: {gl_from} gl_type {gl_to}\n{e}")

                IMPORT_STATUS["links_todo"].remove((j_from, j_type, j_to))
            elif j_type == "clones":
                # No need to perform the cloning, as the cloned issue is already imported.
                # Also, cloned issues become completely independent, so there is no real need to keep trace of this.
                pass
            else:
                print(f"\n[WARN]: Don't know what to do with link type {j_type}!")


def store_import_status():
    with open(IMPORT_STATUS_FILENAME, "wb") as f:
        pickle.dump(IMPORT_STATUS, f, pickle.HIGHEST_PROTOCOL)


def load_import_status():
    try:
        with open(IMPORT_STATUS_FILENAME, "rb") as f:
            import_status = pickle.load(f)
    except (FileNotFoundError, EOFError):
        print("[INFO]: Creating new import_status file")
        import_status = {
            "issue_mapping": dict(),
            "gl_users_made_admin": set(),
            "links_todo": set()
        }

    return import_status


################################################################
# Main body                                                    #
################################################################

# Users that were made admin during the import need to be changed back
def reset_user_privileges():
    print("\nResetting user privileges..\n")

    for gl_username in IMPORT_STATUS["gl_users_made_admin"].copy():
        print(
            f"- User {gl_users[gl_username]['username']} was made admin during the import "
            f"to set the correct timestamps. Turning it back to non-admin.")
        gitlab_user_admin(gl_users[gl_username], False)

    assert (not IMPORT_STATUS["gl_users_made_admin"])


def final_report():
    if jira_users_not_mapped:
        print(f"\nThe following Jira users could not be mapped to Gitlab. "
              f"They have been impersonated by {GITLAB_ADMIN} (number of times):")
        print(f"{json.dumps(jira_users_not_mapped, default=json_encoder, indent=4)}\n")

    if gl_users_not_migrated:
        print(f"\nThe following Jira users could not be found in Gitlab and could not be migrated. "
              f"They have been impersonated by {GITLAB_ADMIN} (number of times)")
        print(f"{json.dumps(gl_users_not_migrated, default=json_encoder, indent=4)}\n")

    if IMPORT_STATUS["gl_users_made_admin"]:
        print("An error occurred while reverting the admin status of Gitlab users.")
        print("IMPORTANT: The following users should be revoked the admin status manually:")
        print(f"{json.dumps(IMPORT_STATUS['gl_users_made_admin'], default=json_encoder, indent=4)}\n")


class SigIntException(Exception):
    pass


def wrapup():
    if IMPORT_SUCCEEDED:
        print("\n\nMigration completed successfully\n")
    else:
        (exctype, _, _) = sys.exc_info()
        if exctype != SigIntException:
            traceback.print_exc()
        print("\n\nMigration failed\n")

    # Users that were made admin during the import need to be changed back
    try:
        reset_user_privileges()
    except Exception as e:
        print(f"\n[ERROR] Could not reset privileges: {e}\n")

    store_import_status()
    final_report()

    if not IMPORT_SUCCEEDED:
        sys.exit(1)


# noinspection PyUnusedLocal
def sigint_handler(signum, frame):
    print("\n\nMigration interrupted (SIGINT)\n")
    raise SigIntException


# Register SIGINT handler, to catch interruptions and wrap up gracefully
signal.signal(signal.SIGINT, sigint_handler)

IMPORT_SUCCEEDED = False

BITBUCKET_COMMIT_PATTERN = ""
if REFERECE_BITBUCKET_COMMITS and BITBUCKET_URL:
    BITBUCKET_COMMIT_PATTERN = re.compile(fr"^{BITBUCKET_URL}/projects/([^/]+)/repos/([^/]+)/commits/\w+$")

if __name__ == "__main__":
    if Path(IMPORT_STATUS_FILENAME).exists():
        continue_pickle = input("Pickle file exists, continue? (y/n)\n")
        if continue_pickle in "nN":
            sys.exit(1)

    # Get available Gitlab namespaces
    gl_namespaces = dict()
    page = 1
    while True:
        rq = requests.get(
            f"{GITLAB_API}/namespaces?page={str(page)}",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE
        )
        rq.raise_for_status()
        for gl_namespace in rq.json():
            gl_namespaces[gl_namespace["full_path"]] = gl_namespace
        if rq.headers["x-page"] != rq.headers["x-total-pages"]:
            page = rq.headers["x-next-page"]
        else:
            break

    # Get available Gitlab users
    gl_users = dict()
    page = 1
    while True:
        rq = requests.get(
            f"{GITLAB_API}/users?page={str(page)}",
            headers={"PRIVATE-TOKEN": GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE
        )
        rq.raise_for_status()
        for _gl_user in rq.json():
            gl_users[_gl_user["username"]] = _gl_user
        if rq.headers["x-page"] != rq.headers["x-total-pages"]:
            page = rq.headers["x-next-page"]
        else:
            break

    # Jira users that could not be mapped to Gitlab users
    jira_users_not_mapped = dict()
    # Gitlab users that were mapped to, but could not be migrated
    gl_users_not_migrated = dict()

    # Load previous import status
    IMPORT_STATUS = load_import_status()

    try:
        # Migrate projects
        for _jira_project, _gitlab_project in PROJECTS.items():
            print(f"\n\nMigrating {_jira_project} to {_gitlab_project}")
            migrate_project(_jira_project, _gitlab_project)
            create_or_update_label_colors(_gitlab_project)

        # Map issue links
        print("\nProcessing links")
        # TODO: There may be some errors in `process_links` for epic issues; not sure; find fix?
        process_links()
        IMPORT_SUCCEEDED = True

    finally:
        wrapup()
