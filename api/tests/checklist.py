"""A practical written through the API for the sign-off tests: the forklift
practical, refreshed every 12 months, and its checklist."""

FORKLIFT = "/v1/practicals/forklift-practical"

ITEMS = ["Checks the forks, chains and tyres", "Lifts a pallet to the top rack",
         "Parks with the forks down"]


def practical(client, headers, refresher_months=12):
    r = client.post("/v1/competencies", headers=headers, json={
        "key": "forklift-practical", "name": "Forklift practical", "kind": "practical",
        "refresher_months": refresher_months})
    assert r.status_code == 201, r.text


def published(client, headers, items=ITEMS, note=None) -> dict:
    """The next version of its checklist."""
    r = client.post(f"{FORKLIFT}/versions", headers=headers, json={"items": items, "note": note})
    assert r.status_code == 201, r.text
    return r.json()
