# jira2gitlab

`jira2gitlab` is a python script to import Jira projects into a Gitlab instance.

At the time of this writing, Gitlab has a nice [Jira integration plugin](https://docs.gitlab.com/ee/integration/jira/). 
While it works well to _connect_ Gitlab to Jira, it is not suited to completely migrate projects and issues,
and eventually shut Jira down.

This script is based on and takes further previous efforts, mainly:
- https://gist.github.com/Gwerlas/980141404bccfa0b0c1d49f580c2d494
- https://gist.github.com/toudi/67d775066334dc024c24

APIs used:
- Jira [API v2](https://docs.atlassian.com/software/jira/docs/api/REST/8.5.0/) (the latest version supported on Jira Server). A password-base login with administrator rights is needed.
- Gitlab [API v4](https://docs.gitlab.com/ee/api/README.html). A token with administration rights is needed.


Tested with:
- Jira Server 8.5.1
- Gitlab 13.11.4-ee Self-Managed

Features:
- Original title, extended with Jira issue key
- Original description, extended with link to Jira issue
- Original comments
- Original labels
- Original attachments
- Original worklogs, as comment + `/spend` quick-action
- Jira comment syntax translated to markdown, including tables
- Jira components are translated to labels
- Jira priority is translated to labels
- Jira status and resolution are translated to labels
- Jira last `fix versions` is translated to milestone
- Jira `relates to` link is translated to `relates_to` link
- Jira `blocks` link is translated to `blocks` link (only Gitlab Premium, otherwise `relates_to`)
- Jira `duplicates` link is translated to `/duplicate` quick-action
- Jira sub-task is translated to an issue with a `blocks` link to the parent issue (only Gitlab Premium, otherwise `relates_to`)
- Epics are currently translated to normal issues and loosely coupled via labels with their child issues
  - TODO: traslated them into Gitlab epics (only Gitlab Premium)
- Multi-project import
- Interrupted imports can be continued




