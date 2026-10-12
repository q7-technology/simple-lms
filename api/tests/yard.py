"""A small training yard for the record and matrix tests, made through the API."""

COMPETENCIES = [
    {"key": "site-induction", "name": "Site induction", "kind": "module", "refresher_months": 24},
    {"key": "forklift-licence", "name": "Forklift licence", "kind": "ticket"},
    {"key": "first-aid", "name": "First aid", "kind": "ticket", "refresher_months": 36},
    {"key": "whs-policy", "name": "WHS policy", "kind": "policy"},
]
ROLES = {
    "forklift-operator": ("Forklift operator", ["site-induction", "forklift-licence"]),
    "picker": ("Picker", ["site-induction"]),
}


def build(client, headers):
    for c in COMPETENCIES:
        assert client.post("/v1/competencies", headers=headers, json=c).status_code == 201
    for key, (name, needs) in ROLES.items():
        assert client.post("/v1/roles", headers=headers, json={"key": key, "name": name}).status_code == 201
        r = client.put(f"/v1/roles/{key}/requirements", headers=headers,
                       json={"competencies": needs})
        assert r.status_code == 200


def give_roles(client, headers, code: str, *roles: str):
    r = client.put(f"/v1/people/{code}/roles", headers=headers, json={"roles": list(roles)})
    assert r.status_code == 200, r.text


def grant(client, headers, code: str, competency: str, granted_on: str, **more):
    r = client.post(f"/v1/people/{code}/records", headers=headers,
                    json={"competency": competency, "granted_on": granted_on, **more})
    assert r.status_code == 201, r.text
    return r.json()
