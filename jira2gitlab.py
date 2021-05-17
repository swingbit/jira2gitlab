# Adapted from https://gist.github.com/Gwerlas/980141404bccfa0b0c1d49f580c2d494
# Inspired to https://gist.github.com/toudi/67d775066334dc024c24

# Jira API documentation : https://docs.atlassian.com/software/jira/docs/api/REST/8.5.0/
# Gitlab API documentation: https://docs.gitlab.com/ee/api/README.html

import requests
from requests.auth import HTTPBasicAuth
import pickle
import re
from io import BytesIO
import os
import uuid
import urllib3

################################################################
# Global variables
################################################################

# Get secrets from environment variables
JIRA_USERNAME = os.getenv("JIRA_USERNAME")
JIRA_PASSWORD = os.getenv("JIRA_PASSWORD")
GITLAB_USERNAME = os.getenv("GITLAB_USERNAME")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")

# check that the secrets are set as environment variables
if None in [JIRA_USERNAME, JIRA_PASSWORD, GITLAB_USERNAME, GITLAB_TOKEN]:
    raise Exception("All the following environment variables must be set:\n" + 
        str(['JIRA_USERNAME', 'JIRA_PASSWORD', 'GITLAB_USERNAME', 'GITLAB_TOKEN'][:-1]))


JIRA_URL = 'https://jira.example.com'
JIRA_API = f'{JIRA_URL}/rest/api/2'
# Admin account used to read from Jira
JIRA_ACCOUNT = (JIRA_USERNAME, JIRA_PASSWORD)
# How many items to request at a time from Jira (usually not more than 1000)
JIRA_PAGINATION_SIZE=100
# the Jira Epic custom field
JIRA_EPIC_FIELD = 'customfield_10103'
# the Jira Sprints custom field
JIRA_SPRINT_FIELD = 'customfield_10340'
# the Jira story points custom field
JIRA_STORY_POINTS_FIELD = 'customfield_10002'

GITLAB_URL = 'https://gitlab.example.com'
GITLAB_API = f'{GITLAB_URL}/api/v4'
# Support Gitlab Premium features (e.g. epics and "bloks" issue links)
GITLAB_PREMIUM = True

# set this to false if JIRA / Gitlab is using self-signed certificate.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
VERIFY_SSL_CERTIFICATE = False

PROJECTS = {
    'PROJECT1': 'group1/project1',
    'PROJECT2': 'group1/project2',
    'PROJECT3': 'group2/project3',
}

# Convert Jira issue types to Gitlab labels
# Unknown issue types are mapped as generic labels
ISSUE_TYPES_MAP = {
    'Bug': 'T::bug',
    'Improvement': 'T::enhancement',
    'New Feature': 'T::new feature',
    'Spike': 'T::spike',
    'Epic': 'T::epic',
    'Story': 'T::story',
    'Task': 'T::task',
    'Sub-task': 'T::task',
}

ISSUE_RESOLUTION_MAP = {
    'Cannot Reproduce': 'S::can\'t reproduce',
    'Duplicate': 'S::duplicate',
    'Incomplete': 'S::incomplete',
    'Won\'t Do': 'S::won\'t do',
    'Won\'t Fix': 'S::won\'t fix',
#    'Unresolved': 'S::unresolved',
#    'Done': 'S::done',
#    'Fixed': 'S::fixed',
}

ISSUE_STATUS_MAP = {
    'Approved': 'S::approved',
    'Awaiting documentation': 'S::needs doc',
    'In Progress': 'S::in progress',
    'In Review': 'S::in review',
    # 'Awaiting payment': '',
    # 'Backlog': '',
    # 'Cancelled': '',
    # 'Closed: '',
    # 'Done': '',
    # 'Open': '',
    # 'Paid': '',
    # 'Rejected': '',
    # 'Reopened': '',
    # 'Resolved': '',
    # 'Selected for Development': '',
}


################################################################
# Functions
################################################################

# Get a specific Jira Issue (for debugging)
def get_jira_issue(issue_key):
    issue = requests.get(
        f'{JIRA_API}/issue/{issue_key}',
        auth=HTTPBasicAuth(*JIRA_ACCOUNT),
        verify=VERIFY_SSL_CERTIFICATE,
        headers={'Content-Type': 'application/json'}
    ).json()
    return issue

# Convert Jira tables to markdown
def jira_table_to_markdown(text):
  lines = text.splitlines()
  # turn in-cell newlines into <br> and reconcatenate mistakenly broken rows
  i = 0
  l = len(lines)
  while i < l:
    j = 0
    if lines[i] and lines[i][0]=='|':
      while i+j < l-1 and lines[i][-1] != '|' :
        j = j + 1
        lines[i] = lines[i] + '<br>' + lines[i+j]
      if i+j == l-1:
        # We reached the end without finding a closing '|'. 
        # Someting is wrong, we abort.
        return text
      for k in range(j):
        lines[i+1+k] = None
    i = i + j + 1

  lines = list(filter(None, lines))

  # Change the ||-delimited header in to |-delimited
  # and insert | --- | separator line
  for i in range(len(lines)):
    if lines[i] and lines[i][:2]=='||' and lines[i][-2:]=='||':
      pp = 0
      p = 0
      for c in lines[i]:
        if c == '|':
          p = p + 1
          if p == 2:
            pp = pp + 1
            p = 0
      sep = '\n' + '| --- ' * (pp - 1) + '|'
      lines[i] = re.sub(r'\|\|', r'|', lines[i]) + sep
  return '\n'.join(lines)


# Gitlab markdown : https://docs.gitlab.com/ee/user/markdown.html
# Jira text formatting notation : https://jira.atlassian.com/secure/WikiRendererHelpAction.jspa?section=all
def multiple_replace(jira_project, text, adict):
    if text is None:
        return ''
    t = text

    # Tables
    t = jira_table_to_markdown(t)

    t = re.sub(r'(\r\n){1}', r'  \1', t) # line breaks
    t = re.sub(r'\{code:([a-z]+)\}\s*', r'\n```\1\n', t) # Block code
    t = re.sub(r'\{code\}\s*', r'\n```\n', t) # Block code
    t = re.sub(r'\n\s*bq\. (.*)\n', r'\n> \1\n', t) # Block quote
    t = re.sub(r'\{quote\}', r'\n>>>\n', t) # Block quote #2
    t = re.sub(r'\{color:[\#\w]+\}(.*)\{color\}', r'> **\1**', t) # Colors
    t = re.sub(r'\n-{4,}\n', r'---', t) # Ruler
    t = re.sub(r'\[~([a-z]+)\]', r'@\1', t) # Links to users
    t = re.sub(r'\[([^|\]]*)\]', r'\1', t) # Links without alt
    t = re.sub(r'\[(?:(.+)\|)([a-z]+://.+)\]', r'[\1](\2)', t) # Links with alt
    t = re.sub(r'(\b%s-\d+\b)' % jira_project, r'[\1](%s/browse/\1)' % JIRA_URL, t) # Links to other issues
    # Lists
    t = re.sub(r'\n *\# ', r'\n 1. ', t) # Ordered list
    t = re.sub(r'\n *[\*\-\#]\# ', r'\n   1. ', t) # Ordered sub-list
    t = re.sub(r'\n *[\*\-\#]{2}\# ', r'\n     1. ', t) # Ordered sub-sub-list
    t = re.sub(r'\n *\* ', r'\n - ', t) # Unordered list
    t = re.sub(r'\n *[\*\-\#][\*\-] ', r'\n   - ', t) # Unordered sub-list
    t = re.sub(r'\n *[\*\-\#]{2}[\*\-] ', r'\n     - ', t) # Unordered sub-sub-list
    # Text effects
    t = re.sub(r'(^|[\W])\*(\S.*\S)\*([\W]|$)', r'\1**\2**\3', t) # Bold
    t = re.sub(r'(^|[\W])_(\S.*\S)_([\W]|$)', r'\1*\2*\3', t) # Emphasis
    t = re.sub(r'(^|[\W])-([^\s\-\|].*[^\s\-\|])-([\W]|$)', r'\1~~\2~~\3', t) # Deleted / Strikethrough
    t = re.sub(r'(^|[\W])\+(\S.*\S)\+([\W]|$)', r'\1__\2__\3', t) # Underline
    t = re.sub(r'(^|[\W])\{\{([^}]*)\}\}([\W]|$)', r'\1`\2`\3', t) # Inline code
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
    #t = re.sub(r'\(off\)', r':', t) # Not found
    t = re.sub(r'\(\*[rgby]?\)', r':star:', t)

    # process custom substitutions
    for k, v in adict.items():
        t = re.sub(k, v, t)
    return t

# Migrate a list of attachments
# We use UUID in place of the filename to prevent 500 errors on unicode chars
# The attachments need to be explicitly mentioned to be visible in Gitlab issues
def move_attachements(attachments, gitlab_project_id):
    replacements = {}
    for attachment in attachments:
        author = attachment['author']['name']

        _file = requests.get(
            attachment['content'],
            auth=HTTPBasicAuth(*JIRA_ACCOUNT),
            verify=VERIFY_SSL_CERTIFICATE,
        )
        if not _file:
            print(f"[WARN] Unable to migrate attachment: {attachment['content']} ... ")
            continue

        _content = BytesIO(_file.content)

        file_info = requests.post(
            f'{GITLAB_API}/projects/{gitlab_project_id}/uploads',
            headers={'PRIVATE-TOKEN': GITLAB_TOKEN,'SUDO': resolve_login(author)},
            files={
                'file': (
                    str(uuid.uuid4()),
                    _content
                )
            },
            verify=VERIFY_SSL_CERTIFICATE
        )
        del _content

        if not file_info:
            print(f"[WARN] Unable to migrate attachment: {attachment['content']} ... ")
            continue

        file_info = file_info.json()

        # Add this to replacements for comments mentioning these attachments
        key = rf"!{re.escape(attachment['filename'])}[^!]*!"
        value = rf"![{attachment['filename']}]({file_info['url']})"
        replacements[key] = value
    return replacements

# Get the ID of a Gitlab milestone name
def get_milestone_id(gl_milestones, gitlab_project_id, string):
    for milestone in gl_milestones:
        if milestone['title'] == string:
            return milestone['id']

    # Milestone doesn't yet exist, so we create it
    milestone = requests.post(
        f'{GITLAB_API}/projects/{gitlab_project_id}/milestones',
        headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
        verify=VERIFY_SSL_CERTIFICATE,
        data={
            'title': string
        }
    )
    if not milestone:
        raise Exception(f"Could not add milestone: {string}")
    
    milestone = milestone.json()
    gl_milestones.append(milestone)
    return milestone['id']

# Find or create the Gitlab user corresponding to the given Jira user
def resolve_login(jira_username):
    if jira_username == 'jira':
        return GITLAB_USERNAME
    for gl_user in gl_users:
	    if gl_user['username'] == jira_username:
		    return gl_user['username']
    
    # it doesn't exist, migrate it.
    return migrate_user(jira_username)

# Migrate a user
def migrate_user(jira_username):
    print(f"\n[INFO] Migrating user {jira_username}")

    if jira_username == 'jira':
        return GITLAB_USERNAME
    jira_user = requests.get(
        f'{JIRA_API}/user?username={jira_username}',
        auth=HTTPBasicAuth(*JIRA_ACCOUNT),
        verify=VERIFY_SSL_CERTIFICATE,
        headers={'Content-Type': 'application/json'}
    ).json()

    gl_user = requests.post(
        f'{GITLAB_API}/users',
        headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
        verify=VERIFY_SSL_CERTIFICATE,
        data={
            'admin': True, # Admin privilege is needed for a correct import, to be removed aferward
            'email': jira_user['emailAddress'],
            'username': jira_username,
            'name': jira_user['displayName'],
            'password': "changeMe"
        }
    ).json()

    gl_users.append(gl_user)
    return jira_username

# Create Gitlab project
def create_gl_project(gitlab_project):
    print(f"\n[INFO] Creating Gitlab project {gitlab_project}")

    [ namespace, project ] = gitlab_project.rsplit('/',1)
    namespace_id = None
    for gl_ns in gl_namespaces:
        if gl_ns['full_path'] == namespace:
            namespace_id = gl_ns['id']
            break
    if namespace_id is None:
        raise(f'Could not find namespace {namespace} in Gitlab!')

    try:
        gl_project = requests.post(
            f'{GITLAB_API}/projects',
            headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE,
            data={
                'path': project,
                'namespace_id': namespace_id,
                'visibility': 'internal',
            }
        )
        gl_project.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to create {gitlab_project} in Gitlab!\n{e}")
    return gl_project.json()['id']

# Migrate a project
def migrate_project(jira_project, gitlab_project):
    # Get the project ID, create it if necessary.
    gitlab_project_id = None
    try:
        projects = requests.get(
            f'{GITLAB_API}/projects',
            headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE
        )
        projects.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to list Gitlab projects!\n{e}")
    projects = projects.json()

    for project in projects:
        if project['path_with_namespace'] == gitlab_project:
            gitlab_project_id = project['id']
            break

    if gitlab_project_id is None:
        gitlab_project_id = create_gl_project(gitlab_project)

    # Load the Gitlab project's milestone list (empty for a new import)
    try:
        gl_milestones = requests.get(
            f'{GITLAB_API}/projects/{gitlab_project_id}/milestones',
            headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
            verify=VERIFY_SSL_CERTIFICATE
        )
        gl_milestones.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Unable to list Gitlab milestones for project {gitlab_project}!\n{e}")
    gl_milestones = gl_milestones.json()

    # Load Jira project issues, with pagination (Jira has a limit on returned items)
    # This assumes they will all fit in memory
    page_start = 0
    jira_issues = []
    while True:
        query = f'{JIRA_API}/search?jql=project="{jira_project}" ORDER BY key&maxResults={str(JIRA_PAGINATION_SIZE)}&startAt={page_start}'
        try:
            jira_issues_batch = requests.get(
                query,
                auth=HTTPBasicAuth(*JIRA_ACCOUNT),
                verify=VERIFY_SSL_CERTIFICATE,
                headers={'Content-Type': 'application/json'}
            )
            jira_issues_batch.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Unable to query {query} in Gitlab!\n{e}")
        jira_issues_batch = jira_issues_batch.json()['issues']
        if not jira_issues_batch:
            break

        page_start = page_start + len(jira_issues_batch)
        jira_issues.extend(jira_issues_batch)
        print(f"\r[INFO] Loading Jira issues from project {jira_project} ... {str(page_start)}", end='', flush=True)
    print("\n")

    # Import issues into Gitlab
    for issue in jira_issues:
        # Skip issues that were already imported
        if issue['key'] in issue_mapping:
            continue

        print(f"\r[INFO] Migrating Jira issue {issue['key']} ...   ", end='', flush=True)

        # Reporter
        reporter = issue['fields']['reporter']['name']

        # Assignee
        gl_assignee = ''
        if issue['fields']['assignee']:
            for user in gl_users:
                if user['username'] == issue['fields']['assignee']['name']:
                    gl_assignee = user['id']
                    break

        # Mark all issues as imported
        labels = ["jira-import"]

        # Migrate existing labels
        labels.extend(issue['fields']['labels'])

        # Issue type to label
        if issue['fields']['issuetype']['name'] in ISSUE_TYPES_MAP:
            labels.append(ISSUE_TYPES_MAP[issue['fields']['issuetype']['name']])
        else:
            print(f"\n[WARN] Jira issue type {issue['fields']['issuetype']['name']} not mapped. Importing as generic label.", flush=True)
            labels.append(issue['fields']['issuetype']['name'])


        # Priority to label (prioritize these labels in Gitlab)
        labels.append('P::' + issue['fields']['priority']['name'].lower())

        # Issue components to labels
        for component in issue['fields']['components']:
            labels.append(component['name'])

        # issue status to label
        if issue['fields']['status'] and issue['fields']['status']['name'] in ISSUE_STATUS_MAP:
            labels.append(ISSUE_STATUS_MAP[issue['fields']['status']['name']])

        # Resolution is also mapped into a status
        if issue['fields']['resolution'] and issue['fields']['resolution']['name'] in ISSUE_RESOLUTION_MAP:
            labels.append(ISSUE_RESOLUTION_MAP[issue['fields']['resolution']['name']])

        # Epic name to label
        if JIRA_EPIC_FIELD in issue['fields'] and issue['fields'][JIRA_EPIC_FIELD]:
            epic_info = requests.get(
                f"{JIRA_API}/issue/{issue['fields'][JIRA_EPIC_FIELD]}/?fields=summary",
                auth=HTTPBasicAuth(*JIRA_ACCOUNT),
                verify=VERIFY_SSL_CERTIFICATE,
                headers={'Content-Type': 'application/json'}
            ).json()
            labels.append(epic_info['fields']['summary'])

        # Last fix versions to milestone
        milestone_id = None
        for fixVersion in issue['fields']['fixVersions']:
            milestone_id = get_milestone_id(gl_milestones, gitlab_project_id, fixVersion['name'])

        # Collect issue links, to be processed after all Gitlab issues are created
        # Only "outward" links were collected.
        # I.e. we only need to process (a blocks b), as (b blocked by a) comes implicitly.
        for link in issue['fields']['issuelinks']:
            if 'outwardIssue' in link:
                links.append( (issue['key'], link['type']['outward'], link['outwardIssue']['key']) )
        
        # There is no sub-task equivalent in Gitlab
        # Use a (sub-task, blocks, task) link instead
        for subtask in issue['fields']['subtasks']:
            links.append( (subtask['key'], "blocks", issue['key']) )

        # Get comments, attachments, and worklogs from Jira
        try:
            issue_extra = requests.get(
                f"{JIRA_API}/issue/{issue['id']}/?fields=attachment,comment,worklog",
                auth=HTTPBasicAuth(*JIRA_ACCOUNT),
                verify=VERIFY_SSL_CERTIFICATE,
                headers={'Content-Type': 'application/json'}
            )
            issue_extra.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Unable to read from Jira issue {issue['key']}")
        issue_extra = issue_extra.json()

        issue['fields']['attachment'] = issue_extra['fields']['attachment']
        issue['fields']['comment'] = issue_extra['fields']['comment']
        issue['fields']['worklog'] = issue_extra['fields']['worklog']
        del issue_extra

        # Migrate attachments and get replacements for comments pointing at them
        replacements = move_attachements(issue['fields']['attachment'], gitlab_project_id)

        # Create Gitlab issue
        # Add a link to the Jira issue and mention all attachments in the description
        gl_description = multiple_replace(jira_project, issue['fields']['description'], replacements)
        gl_description += "\n\n___\n\n"
        gl_description += f"**Imported from Jira issue [{issue['key']}]({JIRA_URL}/browse/{issue['key']})**\n\n"
        for attachment in replacements.values():
            if not attachment in gl_description:
                gl_description += f"Attachment imported from Jira issue [{issue['key']}]({JIRA_URL}/browse/{issue['key']}): {attachment}\n\n"
        try:
            gl_issue = requests.post(
                f"{GITLAB_API}/projects/{gitlab_project_id}/issues",
                headers={'PRIVATE-TOKEN': GITLAB_TOKEN,'SUDO': resolve_login(reporter)},
                verify=VERIFY_SSL_CERTIFICATE,
                data={
                    'created_at': issue['fields']['created'],
                    'assignee_ids': [gl_assignee],
                    'title': f"[{issue['key']}] {issue['fields']['summary']}",
                    'description': gl_description,
                    'milestone_id': milestone_id,
                    'labels': ", ".join(labels),
                }
            )
            gl_issue.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Unable to create Gitlab issue for Jira issue {issue['key']}\n{e}")
        gl_issue = gl_issue.json()

        # Collect Jira-Gitlab ID mapping, to be used later for links
        issue_mapping[issue['key']] = {
            'id': gl_issue['id'],
            'project_id': gl_issue['project_id'],
            'iid': gl_issue['iid'],
            'full_ref': gl_issue['references']['full']
        }

        # If anything after the issue creation fails, remove the issue
        try:
            # Add original comments
            for comment in issue['fields']['comment']['comments']:
                author = comment['author']['name']
                note_add = requests.post(
                    f"{GITLAB_API}/projects/{gitlab_project_id}/issues/{gl_issue['iid']}/notes",
                    headers={'PRIVATE-TOKEN': GITLAB_TOKEN,'SUDO': resolve_login(author)},
                    verify=VERIFY_SSL_CERTIFICATE,
                    data={
                        'created_at': comment['created'],
                        'body': multiple_replace(jira_project, comment['body'], replacements)
                    }
                )
                note_add.raise_for_status()

            # Add worklogs
            for worklog in issue['fields']['worklog']['worklogs']:
                author = worklog['author']['name']
                note_add = requests.post(
                    f"{GITLAB_API}/projects/{gitlab_project_id}/issues/{gl_issue['iid']}/notes",
                    headers={'PRIVATE-TOKEN': GITLAB_TOKEN,'SUDO': resolve_login(author)},
                    verify=VERIFY_SSL_CERTIFICATE,
                    data={
                        'created_at': worklog['started'],
                        'body': f"(Worklog {worklog['timeSpent']})\n\n" 
                                + multiple_replace(jira_project, worklog['comment'], replacements) 
                                + f"\n/spend {worklog['timeSpent']} {worklog['started'][:10]}"
                    }
                )
                note_add.raise_for_status()

            # Close "done" issues
            # status-category can only be "new" (To Do) / "indeterminate" (In Progress) / "done" (Done) / "undefined" (Undefined)
            if issue['fields']['status']['statusCategory']['key'] == "done":
                status = requests.put(
                    f"{GITLAB_API}/projects/{gitlab_project_id}/issues/{gl_issue['iid']}",
                    headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
                    verify=VERIFY_SSL_CERTIFICATE,
                    data={'state_event': 'close'}
                )
                status.raise_for_status()
        except requests.exceptions.RequestException as e:
            requests.delete(
                f"{GITLAB_API}/projects/{gitlab_project_id}/issues/{gl_issue['iid']}",
                headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
                verify=VERIFY_SSL_CERTIFICATE,
            )
            raise Exception(f"Unable to modify Gitlab issue {gl_issue['id']}. Removing issue and aborting.\n{e}")

        # Issue successfully imported.
        # Write current mapping to file
        with open('issue_mapping.pickle', 'wb') as f:
            # Pickle the 'data' dictionary using the highest protocol available.
            pickle.dump(issue_mapping, f, pickle.HIGHEST_PROTOCOL)

def process_links(links):
    for (j_from, j_type, j_to) in links:
        print(f"\r[Info]: Processing link {j_from} {j_type} {j_to}", end='', flush=True)

        if not (j_from in issue_mapping and j_to in issue_mapping):
            print(f"\n[WARN]: Skipping {j_from} {j_type} {j_to}, at least one of the Gitlab issues was not imported")
            continue
        
        gl_from = issue_mapping[j_from]
        gl_to = issue_mapping[j_to]

        # Only "outward" links were collected.
        # I.e. we only need to process (a blocks b), as (b blocked by a) comes implicitly.
        if j_type in ['relates to', 'blocks']:
            if GITLAB_PREMIUM:
                gl_type = j_type.replace(' ', '_')
            else:
                # Gitlab free only support "relates_to" links
                gl_type = 'relates_to'
            try:
                gl_link = requests.post(
                    f"{GITLAB_API}/projects/{gl_from['project_id']}/issues/{gl_from['iid']}/links",
                    headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
                    verify=VERIFY_SSL_CERTIFICATE,
                    data={
                        'target_project_id': gl_to['project_id'],
                        'target_issue_iid': gl_to['iid'],
                        'link_type': gl_type,
                    }
                )
                gl_link.raise_for_status()
            except requests.exceptions.RequestException as e:
                print(f"Unable to create Gitlab issue link: {gl_from} {gl_type} {gl_to}\n{e}")
        else:
            # these Jira links are treated differently in Gitlab
            if j_type == 'duplicates':
                try:
                    note_add = requests.post(
                        f"{GITLAB_API}/projects/{gl_from['project_id']}/issues/{gl_from['iid']}/notes",
                        headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
                        verify=VERIFY_SSL_CERTIFICATE,
                        data={
                            'body': f"/duplicate {gl_to['full_ref']}"
                        }
                    )
                    note_add.raise_for_status()
                except requests.exceptions.RequestException as e:
                    print(f"[WARN] Unable to create Gitlab issue link: {gl_from} {gl_type} {gl_to}\n{e}")
            elif j_type == 'clones':
                # No need to perform the cloning, as the cloned issue is already imported.
                # Also, cloned issues become completely independent, so there is no real need to keep trace of this.
                pass
            else:
                print(f"\n[WARN]: Don't know what to do with link type {j_type}")



################################################################
# Main body
# ################################################################


# Get available Gitlab namespaces
gl_namespaces = requests.get(
    f'{GITLAB_API}/namespaces',
    headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
    verify=VERIFY_SSL_CERTIFICATE
).json()

# Get available Gitlab users
gl_users = requests.get(
    f'{GITLAB_API}/users',
    headers={'PRIVATE-TOKEN': GITLAB_TOKEN},
    verify=VERIFY_SSL_CERTIFICATE
).json()

links = []
issue_mapping = {}

try:
    with open('issue_mapping.pickle', 'rb') as f:
        issue_mapping = pickle.load(f)
except:
    print("[INFO]: Creating new issue mapping file")

# Migrate projects
for jira_project, gitlab_project in PROJECTS.items():
    print(f"\n\nMigrating {jira_project} to {gitlab_project}")
    migrate_project(jira_project, gitlab_project)

# Map issue links
print("\nProcessing links")
process_links(links)

print("\nMigration complete")
