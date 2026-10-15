"""Small files of each kind, and sending one through the API."""

PNG = b"\x89PNG\r\n\x1a\n" + b"signature" * 20
JPEG = b"\xff\xd8\xff\xe0" + b"photo" * 40
PDF = b"%PDF-1.7\n" + b"card" * 40
# an MP4's ftyp box, and a WebM's EBML header naming its DocType
MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"frames" * 40
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\x82\x84webm" + b"frames" * 40
# what an iPhone records: QuickTime, which most browsers won't play
MOV = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"frames" * 40


def send(client, headers, purpose="ticket", data=JPEG, content_type="image/jpeg"):
    return client.post("/v1/uploads", params={"purpose": purpose}, content=data,
                       headers={**headers, "Content-Type": content_type})


def sent(client, headers, purpose="ticket", data=JPEG, content_type="image/jpeg") -> str:
    """The id of a file just sent."""
    r = send(client, headers, purpose, data, content_type)
    assert r.status_code == 201, r.text
    return r.json()["id"]
