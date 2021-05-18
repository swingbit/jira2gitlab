JIRA_URL = 'https://jira.example.com'
JIRA_API = f'{JIRA_URL}/rest/api/2'
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
VERIFY_SSL_CERTIFICATE = False

# Project mapping from Jira to Gitlab
PROJECTS = {
    'PROJECT1': 'group1/project1',
    'PROJECT2': 'group1/project2',
    'PROJECT3': 'group2/project3',
}

# Map Jira issue types to Gitlab labels
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

# Map Jira issue resolutions to Gitlab labels
# Unknown issue resolutions are mapped as generic labels
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

# Map Jira issue statuses to Gitlab labels
# Unknown issue statuses are mapped as generic labels
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
