"""This file and its contents are licensed under the Apache License 2.0. Please see the included NOTICE for copyright information and LICENSE for a copy of the license."""

import logging
import os.path
import re
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import requests
import requests_mock
import ujson as json
from core.feature_flags import flag_set
from data_export.models import ConvertedFormat, Export
from django.apps import apps
from django.conf import settings
from django.test import Client
from ml.models import MLBackend
from organizations.models import Organization
from projects.models import Project
from tasks.serializers import TaskWithAnnotationsSerializer
from users.models import User

try:
    from businesses.models import BillingPlan, Business
except ImportError:
    BillingPlan = Business = None
logger = logging.getLogger(__name__)


@contextmanager
def ml_backend_mock(**kwargs):
    with requests_mock.Mocker(real_http=True) as m:
        yield register_ml_backend_mock(m, **kwargs)


def register_ml_backend_mock(
    m,
    url='http://localhost:9090',
    predictions=None,
    health_connect_timeout=False,
    train_job_id='123',
    setup_model_version='abc',
):
    m.post(f'{url}/setup', text=json.dumps({'status': 'ok', 'model_version': setup_model_version}))
    if health_connect_timeout:
        m.get(f'{url}/health', exc=requests.exceptions.ConnectTimeout)
    else:
        m.get(f'{url}/health', text=json.dumps({'status': 'UP'}))
    m.post(f'{url}/train', text=json.dumps({'status': 'ok', 'job_id': train_job_id}))
    m.post(f'{url}/predict', text=json.dumps(predictions or {}))
    m.post(f'{url}/webhook', text=json.dumps({}))
    m.get(f'{url}/versions', text=json.dumps({'versions': ['1', '2']}))
    return m


@contextmanager
def import_from_url_mock(**kwargs):
    with mock.patch('core.utils.io.validate_url_for_ssrf'):
        with requests_mock.Mocker(real_http=True) as m:
            with open(Path(__file__).parent / 'test_suites' / 'samples' / 'test_1.csv', 'rb') as f:
                matcher = re.compile('data\.heartextest\.net/test_1\.csv')

                m.get(matcher, body=f, headers={'Content-Length': '100'})
                yield m


class _TestJob(object):
    def __init__(self, job_id):
        self.id = job_id


@contextmanager
def email_mock():
    from django.core.mail import EmailMultiAlternatives

    with mock.patch.object(EmailMultiAlternatives, 'send'):
        yield



def upload_data(client, project, tasks):
    tasks = TaskWithAnnotationsSerializer(tasks, many=True).data
    data = [{'data': task['data'], 'annotations': task['annotations']} for task in tasks]
    return client.post(f'/api/projects/{project.id}/tasks/bulk', data=data, content_type='application/json')


def make_project(config, user, use_ml_backend=True, team_id=None, org=None):
    if org is None:
        org = Organization.objects.filter(created_by=user).first()
    project = Project.objects.create(created_by=user, organization=org, **config)
    if use_ml_backend:
        MLBackend.objects.create(project=project, url='http://localhost:8999')

    return project


@pytest.fixture
@pytest.mark.django_db
def project_id(business_client):
    payload = dict(
        title='test_project',
        label_config='<View><Text name="text" value="$text"/><Choices name="test_batch_predictions" toName="text"><Choice value="class_A"/><Choice value="class_B"/></Choices></View>',
    )
    response = business_client.post(
        '/api/projects/',
        data=json.dumps(payload),
        content_type='application/json',
    )
    return response.json()['id']


def make_task(config, project):
    from tasks.models import Task

    return Task.objects.create(project=project, overlap=project.maximum_annotations, **config)


def create_business(user):
    return None


def make_annotation(config, task_id):
    from tasks.models import Annotation, Task

    task = Task.objects.get(pk=task_id)

    return Annotation.objects.create(project_id=task.project_id, task_id=task_id, **config)


def make_prediction(config, task_id):
    from tasks.models import Prediction, Task

    task = Task.objects.get(pk=task_id)
    return Prediction.objects.create(task_id=task_id, project=task.project, **config)


def make_annotator(config, project, login=False, client=None):
    from users.models import User

    user = User.objects.create(**config)
    user.set_password('12345')
    user.save()

    create_business(user)

    if login:
        Organization.create_organization(created_by=user, title=user.first_name)

        if client is None:
            client = Client()
        signin_status_code = signin(client, config['email'], '12345').status_code
        assert signin_status_code == 302, f'Sign-in status code: {signin_status_code}'

    project.add_collaborator(user)
    if login:
        client.annotator = user
        return client
    return user


def invite_client_to_project(client, project):
    if apps.is_installed('annotators'):
        return client.get(f'/annotator/invites/{project.token}/')
    else:
        return SimpleNamespace(status_code=200)


def login(client, email, password):
    if User.objects.filter(email=email).exists():
        r = client.post('/user/login/', data={'email': email, 'password': password})
        assert r.status_code == 302, r.status_code
    else:
        r = client.post('/user/signup/', data={'email': email, 'password': password, 'title': 'Whatever'})
        assert r.status_code == 302, r.status_code


def signin(client, email, password):
    return client.post('/user/login/', data={'email': email, 'password': password})


def signout(client):
    return client.get('/logout')


def _client_is_annotator(client):
    return 'annotator' in client.user.email


def save_response(response):
    fp = os.path.join(settings.TEST_DATA_ROOT, 'tavern-output.json')
    with open(fp, 'w') as f:
        json.dump(response.json(), f)


def os_independent_path(_, path, add_tempdir=False):
    os_independent_path = Path(path)
    if add_tempdir:
        tempdir = Path(tempfile.gettempdir())
        os_independent_path = tempdir / os_independent_path

    os_independent_path_parent = os_independent_path.parent
    return {
        'os_independent_path': str(os_independent_path),
        'os_independent_path_parent': str(os_independent_path_parent),
        'os_independent_path_tmpdir': str(Path(tempfile.gettempdir())),
    }


def verify_docs(response):
    for _, path in response.json()['paths'].items():
        print(path)
        for _, method in path.items():
            print(method)
            if isinstance(method, dict):
                assert 'api' not in method['tags'], f'Need docs for API method {method}'


def empty_list(response):
    assert len(response.json()) == 0, f'Response should be empty, but is {response.json()}'


def save_export_file_path(response):
    export_id = response.json().get('id')
    export = Export.objects.get(id=export_id)
    file_path = export.file.path
    return {'file_path': file_path}


def save_convert_file_path(response, export_id=None):
    export = response.json()[0]
    convert = export['converted_formats'][0]

    converted = ConvertedFormat.objects.get(id=convert['id'])

    dir_path = os.path.join(settings.MEDIA_ROOT, settings.DELAYED_EXPORT_DIR)
    os.listdir(dir_path)
    try:
        file_path = converted.file.path
        return {'convert_file_path': file_path}
    except ValueError:
        return {'convert_file_path': None}


def file_exists_in_storage(response, exists=True, file_path=None):
    if not file_path:
        export_id = response.json().get('id')
        export = Export.objects.get(id=export_id)
        file_path = export.file.path

    assert os.path.isfile(file_path) == exists


def mock_feature_flag(flag_name: str, value: bool, parent_module: str = 'core.feature_flags'):
    """Decorator to mock a feature flag state for a test function.

    Args:
        flag_name: Name of the feature flag to mock
        value: True or False to set the flag state
        parent_module: Module path containing the flag_set function to patch
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            def fake_flag_set(feature_flag, *flag_args, **flag_kwargs):
                if feature_flag == flag_name:
                    return value
                return flag_set(feature_flag, *flag_args, **flag_kwargs)

            with mock.patch(f'{parent_module}.flag_set', wraps=fake_flag_set):
                return func(*args, **kwargs)

        return wrapper

    return decorator
