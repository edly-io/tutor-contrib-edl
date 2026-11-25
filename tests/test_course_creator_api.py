"""Standalone tests for the Studio course creator API."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework.test import APIRequestFactory, force_authenticate

from edl_plugin.course_creator_api import service
from edl_plugin.course_creator_api.views import CourseCreatorAccessView


@pytest.fixture
def platform(monkeypatch, db):
    """Provide the platform models and role repair function."""
    users = get_user_model().objects
    caller = users.create(username="edl_portal_service", is_staff=True)
    target = users.create(username="target")
    events = []
    rows = []
    records = {}

    class Orgs:
        def __init__(self):
            self.names = []

        def values_list(self, *args, **kwargs):
            return self.names[:]

        def set(self, objects):
            events.append("set")
            self.names = [obj.short_name for obj in objects]

        def clear(self):
            events.append("clear")
            self.names = []

    class Creator:
        UNREQUESTED = "unrequested"
        GRANTED = "granted"
        STATES = [(x, x) for x in ("unrequested", "pending", "granted", "denied")]

        def __init__(self):
            self.state = "unrequested"
            self.all_organizations = True
            self.organizations = Orgs()

        def save(self):
            assert self.admin == caller
            events.append(("save", self.state, self.all_organizations))

    def get_or_create(user):
        if user.pk not in records:
            records[user.pk] = Creator()
            return records[user.pk], True
        return records[user.pk], False

    Creator.objects = SimpleNamespace(
        get_or_create=get_or_create,
        filter=lambda user: SimpleNamespace(first=lambda: records.get(user.pk)),
    )
    orgs = [SimpleNamespace(short_name=name) for name in ("OrgA", "OrgB")]
    organization = SimpleNamespace(objects=SimpleNamespace(filter=lambda **kwargs: [
        org for org in orgs if org.short_name.lower() in [x.lower() for x in kwargs["short_name__in"]]
    ]))

    def repair(caller_arg, user, names):
        assert caller_arg == caller
        events.append(("repair", names[:]))
        rows[:] = sorted(names)

    for name, attrs in {
        "cms.djangoapps.course_creators.models": {"CourseCreator": Creator},
        "cms.djangoapps.course_creators.views": {"update_org_content_creator_role": repair},
        "organizations.models": {"Organization": organization},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    read_rows = service._rows
    monkeypatch.setattr(service, "_rows", lambda user: (rows[:], False))
    return SimpleNamespace(
        caller=caller, target=target, records=records, events=events, rows=rows, Creator=Creator, read_rows=read_rows
    )


def test_grant_repeat_change_and_revoke(platform):
    result = service.set_state("target", True, ["OrgA", "OrgA"], "admin")
    assert result["granted_orgs"] == ["OrgA"]
    assert platform.events[:3] == [("save", "granted", False), "set", ("repair", ["OrgA"])]
    platform.events.clear()
    assert not service.set_state("target", True, ["OrgA"], "admin")["changed"]
    assert platform.events[-1] == ("repair", ["OrgA"])
    result = service.set_state("target", True, ["OrgB"], "admin")
    assert result["removed_orgs"] == ["OrgA"]
    platform.events.clear()
    service.set_state("target", False, [], "admin")
    assert platform.events == [("save", "unrequested", False), "clear", ("repair", [])]


@pytest.mark.parametrize("state", ["pending", "denied"])
def test_off_preserves_pending_and_denied(platform, state):
    record, _ = platform.Creator.objects.get_or_create(platform.target)
    record.state = state
    service.set_state("target", False, [], "admin")
    assert record.state == state
    assert platform.events == ["clear", ("repair", [])]


@pytest.mark.parametrize("admin,orgs,code", [
    (True, [], "organizations_required"), (False, ["OrgA"], "organizations_not_allowed"),
    (True, ["orga"], "unknown_organizations"),
])
def test_validation(platform, admin, orgs, code):
    with pytest.raises(service.CourseCreatorError) as exc:
        service.set_state("target", admin, orgs, "admin")
    assert exc.value.code == code
    assert not platform.events


def test_user_and_service_validation(platform):
    for user, field, code in [(platform.target, "is_active", "user_inactive"),
                              (platform.target, "is_staff", "user_is_global_staff"),
                              (platform.caller, "is_active", "service_account_not_set_up")]:
        original = getattr(user, field)
        setattr(user, field, not original)
        user.save()
        with pytest.raises(service.CourseCreatorError) as exc:
            service.set_state("target", True, ["OrgA"], "admin")
        assert exc.value.code == code
        setattr(user, field, original)
        user.save()
    with pytest.raises(service.CourseCreatorError) as exc:
        service.get_state("missing")
    assert exc.value.code == "user_not_found"


def test_global_downgrade_and_restore(platform):
    record, _ = platform.Creator.objects.get_or_create(platform.target)
    record.state = "granted"
    token = service.get_state("target")["snapshot_token"]
    with pytest.raises(service.CourseCreatorError) as exc:
        service.set_state("target", True, ["OrgA"], "admin")
    assert exc.value.code == "global_creator_downgrade"
    assert not platform.events
    service.set_state("target", True, ["OrgA"], "admin", True)
    assert not record.all_organizations
    service.restore_state("target", token, "admin")
    assert record.state == "granted" and record.all_organizations
    assert platform.rows == []


def test_snapshot_and_invalid_restore(platform, monkeypatch):
    snapshot = service.get_state("target")
    assert snapshot["state"] is None and snapshot["all_organizations"] is None
    decoded = signing.loads(snapshot["snapshot_token"], salt=service.SALT)
    assert decoded == {key: snapshot[key] for key in ("username", "state", "all_organizations", "organizations")}
    for token in (snapshot["snapshot_token"] + "x", signing.dumps({**decoded, "username": "other"}, salt=service.SALT)):
        with pytest.raises(service.CourseCreatorError) as exc:
            service.restore_state("target", token, "admin")
        assert exc.value.code == "invalid_restore"
    loads = signing.loads
    monkeypatch.setattr(service.signing, "loads", Mock(side_effect=signing.SignatureExpired()))
    with pytest.raises(service.CourseCreatorError) as exc:
        service.restore_state("target", snapshot["snapshot_token"], "admin")
    assert exc.value.code == "invalid_restore"
    monkeypatch.setattr(service.signing, "loads", loads)
    assert not platform.events


def test_endpoint_auth_and_errors(platform):
    factory = APIRequestFactory()
    view = CourseCreatorAccessView.as_view()
    response = view(factory.get("/"), username="target")
    assert response.status_code in (401, 403)
    request = factory.get("/")
    force_authenticate(request, user=platform.target)
    response = view(request, username="target")
    assert response.status_code == 403 and response.data["code"] == "not_service_account"
    platform.caller.is_staff = False
    request = factory.get("/")
    force_authenticate(request, user=platform.caller)
    response = view(request, username="target")
    assert response.status_code == 403 and response.data["code"] == "not_service_account"
    platform.caller.is_staff = True
    request = factory.post("/", {"org_admin": True, "organizations": []}, format="json")
    force_authenticate(request, user=platform.caller)
    response = view(request, username="target")
    assert response.status_code == 400 and response.data["code"] == "organizations_required"
    assert response["Cache-Control"] == "no-store"


def test_restore_default_record_and_confirmed_revoke(platform):
    record, _ = platform.Creator.objects.get_or_create(platform.target)
    token = service.get_state("target")["snapshot_token"]
    service.set_state("target", True, ["OrgA"], "admin")
    service.restore_state("target", token, "admin")
    assert record.state == "unrequested" and record.all_organizations
    record.state = "granted"
    platform.events.clear()
    service.set_state("target", False, [], "admin", True)
    assert platform.events == [("save", "unrequested", True), "clear", ("repair", [])]


def test_writes_are_inside_atomic(platform, monkeypatch):
    active = []

    class Atomic:
        def __enter__(self):
            active.append(True)

        def __exit__(self, *args):
            active.pop()

    original = platform.Creator.save

    def save(record):
        assert active
        return original(record)

    monkeypatch.setattr(service.transaction, "atomic", Atomic)
    monkeypatch.setattr(platform.Creator, "save", save)
    service.set_state("target", True, ["OrgA"], "admin")
    token = service.get_state("target")["snapshot_token"]
    service.restore_state("target", token, "admin")
    assert not active


def test_read_role_rows_uses_blank_course(platform, monkeypatch):
    query = Mock()
    query.filter.side_effect = [SimpleNamespace(values_list=lambda *args, **kwargs: ["OrgB", "OrgA"]),
                                SimpleNamespace(exists=lambda: True)]
    manager = Mock()
    manager.filter.return_value = query
    module = ModuleType("common.djangoapps.student.models")
    module.CourseAccessRole = SimpleNamespace(objects=manager)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert platform.read_rows(platform.target) == (["OrgA", "OrgB"], True)
    manager.filter.assert_called_once_with(user=platform.target, course_id=None)


def test_endpoint_get_and_restore(platform):
    factory = APIRequestFactory()
    view = CourseCreatorAccessView.as_view()
    request = factory.get("/")
    force_authenticate(request, user=platform.caller)
    response = view(request, username="target")
    assert response.status_code == 200 and response.data["state"] is None
    token = response.data["snapshot_token"]
    request = factory.post("/", {"org_admin": True, "organizations": ["OrgA"]}, format="json")
    force_authenticate(request, user=platform.caller)
    assert view(request, username="target").data["state"] == "granted"
    request = factory.post("/", {"restore_token": token}, format="json")
    force_authenticate(request, user=platform.caller)
    assert view(request, username="target").data["state"] == "unrequested"
