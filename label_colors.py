import requests
import urllib.parse

from jira2gitlab_secrets import *
from jira2gitlab_config import *


def get_project_id(project_path):
    project = requests.get(
        f"{GITLAB_API}/projects/{urllib.parse.quote(project_path, safe='')}",
        headers = {'PRIVATE-TOKEN': GITLAB_TOKEN},
        verify = VERIFY_SSL_CERTIFICATE
    )
    return project.json()['id']


def get_labels(project_id):
    result = []
    page = 1
    while True:
        next_labels = requests.get(
            f'{GITLAB_API}/projects/{project_id}/labels',
            params = {"per_page": 100, "page": page},
            headers = {'PRIVATE-TOKEN': GITLAB_TOKEN},
            verify = VERIFY_SSL_CERTIFICATE,
        ).json()
        if not next_labels:
            return result
        result.extend(next_labels)
        page += 1


def update_label_color(project_id, label_id, label_color):
    requests.put(
        f'{GITLAB_API}/projects/{project_id}/labels/{label_id}',
        headers = {'PRIVATE-TOKEN': GITLAB_TOKEN},
        verify = VERIFY_SSL_CERTIFICATE,
        json = {"color": label_color}
    )


def create_label(project_id, label_name, label_color):
    requests.post(
        f'{GITLAB_API}/projects/{project_id}/labels',
        headers = {'PRIVATE-TOKEN': GITLAB_TOKEN},
        verify = VERIFY_SSL_CERTIFICATE,
        json = {"name": label_name, "color": label_color}
    )


def create_or_update_label_colors(gitlab_project):
    print(f"\n\nUpdating label colors for {gitlab_project}")
    project_id = get_project_id(gitlab_project)
    existing_labels = get_labels(project_id)
    for label_name, label_color in LABEL_COLORS.items():
        existing_label = next((x for x in existing_labels if x["name"] == label_name), None)
        if existing_label:
            if existing_label["color"] != label_color:
                update_label_color(project_id, existing_label["id"], label_color)
        else:
            create_label(project_id, label_name, label_color)


if __name__ == "__main__":
    for jira_project, gitlab_project in PROJECTS.items():
        create_or_update_label_colors(gitlab_project)
