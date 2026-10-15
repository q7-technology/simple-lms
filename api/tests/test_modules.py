"""Modules, as their editors write them: a draft of pages and a quiz,
saved in full, then published and frozen. A change after that is a new
version."""
import pytest

import yard
from course import INDUCTION, QUESTIONS, save, written
from files import JPEG, MP4, sent


@pytest.fixture
def induction(client, manager_headers):
    yard.build(client, manager_headers)


def test_a_module_starts_as_an_empty_draft(client, manager_headers, induction):
    assert client.get(f"{INDUCTION}/versions", headers=manager_headers).json() == []
    r = client.post(f"{INDUCTION}/draft", headers=manager_headers)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["version"], out["pass_mark"], out["published_at"]) == (1, 80, None)
    assert (out["pages"], out["questions"]) == ([], [])


def test_the_draft_is_saved_in_full(client, manager_headers, induction):
    out = written(client, manager_headers)
    assert [p["kind"] for p in out["pages"]] == ["text", "image", "pdf", "video", "link"]
    text, image, pdf, video, link = out["pages"]
    assert text["body"] == "Sign in at the gatehouse.\nWear your PPE." and text["file"] is None
    assert image["body"] == "Walk inside the green lines."
    assert (video["file"]["content_type"], video["file"]["size_bytes"]) == ("video/mp4", len(MP4))
    assert video["file"]["link"].startswith(f"/v1/media/{video['file']['id']}?session=")
    assert pdf["body"] is None and link["url"] == "https://www.safework.nsw.gov.au"
    assert out["questions"] == QUESTIONS


def test_saving_again_replaces_it(client, manager_headers, induction):
    out = written(client, manager_headers)
    text, image, *_ = out["pages"]
    kept = [{"kind": "image", "title": image["title"], "file": image["file"]["id"]},
            {"kind": "text", "title": text["title"], "body": text["body"]}]
    r = save(client, manager_headers, pass_mark=70, pages=kept, questions=QUESTIONS[1:])
    assert r.status_code == 200, r.text
    out = r.json()
    assert [p["title"] for p in out["pages"]] == ["The yard", "Welcome"]
    assert out["pass_mark"] == 70 and len(out["questions"]) == 1


@pytest.mark.parametrize("page, field, message", [
    ({"kind": "text", "title": "Welcome"}, "pages.0.body", "a text page needs its text"),
    ({"kind": "video", "title": "Lifting"}, "pages.0.file", "add the video"),
    ({"kind": "link", "title": "SafeWork"}, "pages.0.url",
     "a link is a web address starting with https://"),
    ({"kind": "link", "title": "SafeWork", "url": "javascript:alert(1)"}, "pages.0.url",
     "a link is a web address starting with https://"),
    ({"kind": "link", "title": "SafeWork", "url": "https://"}, "pages.0.url",
     "a link is a web address starting with https://"),
    ({"kind": "link", "title": "SafeWork", "url": "https:///x"}, "pages.0.url",
     "a link is a web address starting with https://"),
    ({"kind": "link", "title": "SafeWork", "url": "https://example.com.au/a b"}, "pages.0.url",
     "a link is a web address starting with https://"),
    ({"kind": "text", "title": "Welcome", "body": "Hi.", "url": "https://example.com.au"},
     "pages.0.url", "only a link page has a web address"),
])
def test_each_page_has_what_its_kind_needs(client, manager_headers, induction, page, field,
                                           message):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    r = save(client, manager_headers, pages=[page])
    assert r.status_code == 422 and r.json()["errors"] == [{"field": field, "message": message}]


def test_a_link_to_a_page_on_a_site_is_kept(client, manager_headers, induction):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    page = {"kind": "link", "title": "SafeWork", "url": "https://example.com.au/path"}
    r = save(client, manager_headers, pages=[page])
    assert r.status_code == 200, r.text
    assert r.json()["pages"][0]["url"] == "https://example.com.au/path"


def test_a_pages_file_is_a_page_file_of_its_kind(client, manager_headers, induction):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    picture = sent(client, manager_headers, "page-image", JPEG)
    photo = sent(client, manager_headers, "ticket", JPEG)
    for file in (picture, photo):
        r = save(client, manager_headers, pages=[{"kind": "video", "title": "Lifting",
                                                  "file": file}])
        assert r.status_code == 422 and r.json()["errors"] == [{
            "field": "pages.0.file",
            "message": "that file isn't a video for a page: send it again"}]


@pytest.mark.parametrize("question, field", [
    ({"prompt": "Well?", "options": ["Yes", "No"], "correct": 2}, "questions.0.correct"),
    ({"prompt": "Well?", "options": ["Yes"], "correct": 0}, "questions.0.options"),
    ({"prompt": "Well?", "options": ["Yes", "  "], "correct": 0}, "questions.0.options.1"),
    ({"prompt": "Well?", "options": list("abcdefg"), "correct": 0}, "questions.0.options"),
])
def test_a_question_has_two_to_six_answers_and_one_is_right(client, manager_headers, induction,
                                                            question, field):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    r = save(client, manager_headers, questions=[question])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == field


def test_publishing_freezes_it_and_a_change_is_a_new_version(client, manager_headers, induction):
    written(client, manager_headers)
    r = client.post(f"{INDUCTION}/draft/publish", headers=manager_headers)
    assert r.status_code == 200, r.text
    one = r.json()
    assert one["published_at"] and one["published_by"] == {"code": "MG001", "name": "Mel Grant"}
    r = save(client, manager_headers, pages=[{"kind": "text", "title": "x", "body": "y"}])
    assert r.status_code == 404 and r.json()["detail"] == "Site induction has no draft: start one"
    # the next version starts as a copy of the last, and changes alone
    r = client.post(f"{INDUCTION}/draft", headers=manager_headers)
    two = r.json()
    assert two["version"] == 2 and two["published_at"] is None
    assert [p["title"] for p in two["pages"]] == [p["title"] for p in one["pages"]]
    assert two["questions"] == one["questions"]
    save(client, manager_headers, pages=[{"kind": "text", "title": "New", "body": "New."}],
         questions=QUESTIONS[:1])
    versions = client.get(f"{INDUCTION}/versions", headers=manager_headers).json()
    assert [(v["version"], len(v["pages"])) for v in versions] == [(2, 1), (1, 5)]


def test_publishing_needs_a_page_and_a_question(client, manager_headers, induction):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    save(client, manager_headers, pages=[{"kind": "text", "title": "Hi", "body": "Hi."}])
    r = client.post(f"{INDUCTION}/draft/publish", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "incomplete"


def test_one_draft_at_a_time(client, manager_headers, induction):
    client.post(f"{INDUCTION}/draft", headers=manager_headers)
    r = client.post(f"{INDUCTION}/draft", headers=manager_headers)
    assert r.status_code == 409 and r.json() == {
        "detail": "version 1 is being written already", "code": "draft_exists"}


def test_only_a_module_has_versions(client, manager_headers, induction):
    r = client.post("/v1/modules/whs-policy/draft", headers=manager_headers)
    assert r.status_code == 404 and r.json()["detail"] == "no module whs-policy"
    r = client.get("/v1/modules/nothing/versions", headers=manager_headers)
    assert r.status_code == 404 and r.json()["detail"] == "no competency nothing"


def test_only_an_editor_writes_one(client, learner_headers, supervisor_headers, manager_headers,
                                   induction):
    for headers in (learner_headers, supervisor_headers):
        assert client.post(f"{INDUCTION}/draft", headers=headers).status_code == 403
    assert client.get(f"{INDUCTION}/versions", headers=supervisor_headers).status_code == 200
    assert client.get(f"{INDUCTION}/versions", headers=learner_headers).status_code == 403


def test_a_deactivated_module_gets_no_new_version(client, manager_headers, induction):
    written(client, manager_headers)
    client.post("/v1/competencies/site-induction/deactivate", headers=manager_headers)
    r = client.post(f"{INDUCTION}/draft/publish", headers=manager_headers)
    assert r.status_code == 409 and r.json()["code"] == "inactive"
