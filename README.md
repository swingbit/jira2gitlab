# jira2gitlab

`jira2gitlab` is a python script to import Jira projects into a Gitlab instance.

At the time of this writing, Gitlab has a nice [Jira integration plugin](https://docs.gitlab.com/ee/integration/jira/). 
While it works well to _connect_ Gitlab to Jira, it is not (yet) suited to completely migrate projects and issues,
and eventually shut Jira down.

This script is based on and takes further previous efforts, mainly https://gist.github.com/Gwerlas/980141404bccfa0b0c1d49f580c2d494


APIs used:
- Jira [API v2](https://docs.atlassian.com/software/jira/docs/api/REST/8.5.0/) (the latest version supported on Jira Server). A password-based login with administrator rights is needed.
- Gitlab [API v4](https://docs.gitlab.com/ee/api/README.html). An access token with administration rights is needed.


Tested with:
- Jira Server 8.5.1
- Gitlab Self-Managed 14.7.0-ee

## Features:
- Original title, extended with Jira issue key
- Original description, extended with link to Jira issue
- Original comments
- Original labels
- Original attachments
- Original worklogs, as comment + `/spend` quick-action
- Issue references in commits from a linked Bitbucket Server are translated to Gitlab issue references
(with some limitations, read instructions in config file)
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
  - TODO: traslate them into Gitlab epics (only Gitlab Premium)
- Users can be created automatically, with username mapping specified in the configuration
  - All Gitlab users used/created in Gitlab can be given admin rights (configurable) during the import (needed to import timestamps correctly).
At the end of the import, as well as upon unexpected exit, the assigned admin rights are revoked.
Should this last step fail for any reason, a list of admin rights to be revoked manually is reported.
  - All Jira users that could not be mapped and/or created on Gitlab are reported at the end of the import.
  - **WARNING**: all users that are created in Gitlab are given the password `changeMe`. You know what to do ;)
- Multi-project import (projects are created automatically, but not groups)
- Interrupted imports can be continued
- Incremental import: it can be run multiple times, it will update issues that have changed since last import (provided that the `import_status.pickle` file from the previous run is available)

## Usage
- Make sure you can use an admin user on Jira
- Create an access token with full rights on Gitlab
- Customize `jira2gitlab_config.py` (check carefully all the options) and `jira2gitlab_secrets.py`
- Create all required groups and subgroups in Gitlab, according to your project mapping.
The script creates the projects themselves, but not the groups.
- Install the requirements and run the script:
```
pip install -r requirements
python jira2gitlab.py
```
- If the script was interrupted, or if some issues were updated in Jira, you can run the script again.
Only the differences will be imported (as long as you keep the `import_status.pickle` file)




