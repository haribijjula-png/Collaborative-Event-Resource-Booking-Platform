import io
import zipfile

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%fake\n" + b"x" * 50


def up(w, ev, name, content, mime, user=None, **form):
    return w.c.post("/api/files", data={"event_id": ev["id"], "entity_type": "event", **form}, files={"file": (name, content, mime)}, headers=(user or w.manager)["h"])


def test_valid_upload_list_download_delete(w):
    ev = w.event()
    r = up(w, ev, "agenda.pdf", PDF, "application/pdf")
    assert r.status_code == 201
    d = r.json()["data"]
    assert d["mime_type"] == "application/pdf" and d["file_size"] == len(PDF) and d["file_name"] == "agenda.pdf"
    assert "storage_path" not in d                                   # internal path never leaked
    assert len(w.c.get(f"/api/events/{ev['id']}/files", headers=w.p1["h"]).json()["data"]) == 1
    dl = w.c.get(f"/api/files/{d['id']}/download", headers=w.p1["h"])
    assert dl.status_code == 200 and dl.content == PDF
    assert w.c.get(f"/api/files/{d['id']}/download", headers=w.admin_b["h"]).status_code == 404
    assert w.c.delete(f"/api/files/{d['id']}", headers=w.p1["h"]).status_code == 403
    assert w.c.delete(f"/api/files/{d['id']}", headers=w.manager["h"]).status_code == 200


def test_valid_png_docx_and_text(w):
    ev = w.event()
    assert up(w, ev, "logo.png", PNG, "image/png").status_code == 201
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w/>")
    assert up(w, ev, "brief.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document").status_code == 201
    assert up(w, ev, "notes.txt", b"hello world", "text/plain").status_code == 201


def test_invalid_extension_rejected(w):
    ev = w.event()
    for name in ("run.exe", "page.html", "script.sh", "noext", "evil.php"):
        r = up(w, ev, name, b"hello", "text/plain")
        assert r.status_code == 415 and r.json()["error"]["code"] == "INVALID_FILE_EXTENSION", name


def test_content_must_match_extension(w):
    ev = w.event()
    # an executable renamed to .pdf / .png is caught by content sniffing
    r = up(w, ev, "invoice.pdf", b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 40, "application/pdf")
    assert r.status_code == 415 and r.json()["error"]["code"] == "INVALID_FILE_TYPE"
    assert up(w, ev, "photo.png", PDF, "image/png").json()["error"]["code"] == "INVALID_FILE_TYPE"     # real PDF named .png
    assert up(w, ev, "doc.docx", b"PK\x03\x04garbage", "application/zip").status_code == 415            # broken zip
    assert up(w, ev, "data.csv", b"\xff\xfe\x00\x01binary\x00", "text/csv").status_code == 415


def test_client_mime_lie_rejected(w):
    ev = w.event()
    r = up(w, ev, "logo.png", PNG, "application/pdf")
    assert r.status_code == 415 and r.json()["error"]["code"] == "INVALID_MIME_TYPE"


def test_oversized_file_rejected(w):
    ev = w.event()                                                   # MAX_UPLOAD_MB=1 in tests
    r = up(w, ev, "big.pdf", b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10), "application/pdf")
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert up(w, ev, "empty.pdf", b"", "application/pdf").status_code == 400


def test_path_traversal_filename_is_sanitised(w):
    ev = w.event()
    r = up(w, ev, "../../etc/passwd.txt", b"hi", "text/plain")
    assert r.status_code == 201 and r.json()["data"]["file_name"] == "passwd.txt"


def test_upload_permissions(w):
    ev = w.event()
    assert up(w, ev, "a.pdf", PDF, "application/pdf", user=w.p1).status_code == 403          # participants can't add event docs
    assert up(w, ev, "a.pdf", PDF, "application/pdf", user=w.admin_b).status_code == 404     # other org
    reg = w.register(w.p1, ev).json()["data"]
    r = up(w, ev, "id.pdf", PDF, "application/pdf", user=w.p1, entity_type="registration", entity_id=reg["id"])
    assert r.status_code == 201
    assert up(w, ev, "id.pdf", PDF, "application/pdf", user=w.p2, entity_type="registration", entity_id=reg["id"]).status_code == 403
    att = r.json()["data"]
    assert w.c.get(f"/api/files/{att['id']}/download", headers=w.p2["h"]).status_code == 403
    assert w.c.get(f"/api/files/{att['id']}/download", headers=w.staff["h"]).status_code == 200
    assert att["id"] not in [f["id"] for f in w.c.get(f"/api/events/{ev['id']}/files", headers=w.p2["h"]).json()["data"]]
    assert up(w, ev, "x.pdf", PDF, "application/pdf", entity_type="bogus").status_code == 400
