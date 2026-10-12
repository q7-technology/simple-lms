import csv
import io

import yard
from conftest import make_person


def test_the_matrix_as_a_spreadsheet(client, db, manager_headers, learner):
    yard.build(client, manager_headers)
    yard.give_roles(client, manager_headers, "LL042", "forklift-operator")
    yard.grant(client, manager_headers, "LL042", "forklift-licence", "2025-01-01",
               expires_on="2026-11-01")
    r = client.get("/v1/matrix.csv?role=forklift-operator", headers=manager_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="matrix-2026-10-12.csv"' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows == [
        ["code", "name", "roles", "supervisor", "Forklift licence", "Forklift licence expires",
         "Site induction", "Site induction expires"],
        ["LL042", "Kim Lee", "Forklift operator", "Sam Vu", "expiring", "2026-11-01",
         "missing", ""],
    ]


def test_a_cell_that_looks_like_a_formula_is_not_one(client, db, manager_headers):
    yard.build(client, manager_headers)
    make_person(db, "LL077", "=HYPERLINK(\"http://example.com\")")
    yard.give_roles(client, manager_headers, "LL077", "picker")
    rows = list(csv.reader(io.StringIO(
        client.get("/v1/matrix.csv", headers=manager_headers).text)))
    assert rows[1][1].startswith("'=")


def test_the_spreadsheet_needs_the_matrix_scope(client, learner_headers):
    assert client.get("/v1/matrix.csv", headers=learner_headers).status_code == 403
