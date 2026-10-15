"""A module written through the API for the module tests: site induction,
with a page of each kind and two questions."""
from files import JPEG, MP4, PDF, sent

INDUCTION = "/v1/modules/site-induction"

QUESTIONS = [
    {"prompt": "Where do you sign in?", "options": ["The gatehouse", "The canteen"], "correct": 0},
    {"prompt": "What do you wear on the floor?",
     "options": ["Thongs", "Your PPE", "Anything"], "correct": 1},
]
# what gets both questions right
RIGHT = [0, 1]


def pages(client, headers) -> list[dict]:
    """One page of each kind."""
    return [
        {"kind": "text", "title": "Welcome", "body": "Sign in at the gatehouse.\nWear your PPE."},
        {"kind": "image", "title": "The yard", "body": "Walk inside the green lines.",
         "file": sent(client, headers, "page-image", JPEG)},
        {"kind": "pdf", "title": "Site map",
         "file": sent(client, headers, "page-pdf", PDF, "application/pdf")},
        {"kind": "video", "title": "Lifting safely",
         "file": sent(client, headers, "page-video", MP4, "video/mp4")},
        {"kind": "link", "title": "SafeWork", "url": "https://www.safework.nsw.gov.au"},
    ]


def save(client, headers, **body):
    """The draft in full; nothing but what is given."""
    return client.put(f"{INDUCTION}/draft", headers=headers,
                      json={"pass_mark": 80, "pages": [], "questions": [], **body})


def written(client, headers, questions=QUESTIONS, pass_mark=80) -> dict:
    """The next version started and saved with a page of each kind and the questions."""
    assert client.post(f"{INDUCTION}/draft", headers=headers).status_code == 201
    r = save(client, headers, pass_mark=pass_mark, pages=pages(client, headers),
             questions=questions)
    assert r.status_code == 200, r.text
    return r.json()


def published(client, headers, **more) -> dict:
    """Written, then published."""
    written(client, headers, **more)
    r = client.post(f"{INDUCTION}/draft/publish", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()
