"""Small files of each kind, and sending one through the API."""

PNG = b"\x89PNG\r\n\x1a\n" + b"signature" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 40
PDF = b"%PDF-1.7\n" + b"card" * 40


def send(client, headers, purpose="ticket", data=JPEG, content_type="image/jpeg"):
    return client.post("/v1/uploads", params={"purpose": purpose}, content=data,
                       headers={**headers, "Content-Type": content_type})


def sent(client, headers, purpose="ticket", data=JPEG, content_type="image/jpeg") -> str:
    """The id of a file just sent."""
    r = send(client, headers, purpose, data, content_type)
    assert r.status_code == 201, r.text
    return r.json()["id"]
