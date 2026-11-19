import asyncio
import os
import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock

import bot
from bot import parse_student_line, bootstrap_student_data


def test_parse_student_line_science_record():
    line = "99999-00000001 2099 TEST STUDENT 01-01-2000 TEST FATHER FemaleEWS NO SCIENCE 500 465 93.00"
    student = parse_student_line(line, "SCIENCE")

    assert student is not None
    assert student["RollCode"] == "99999"
    assert student["RollNumber"] == "00000001"
    assert student["StudentName"] == "TEST STUDENT"
    assert student["DOB"] == "01-01-2000"
    assert student["FatherName"] == "TEST FATHER"
    assert student["Gender"] == "Female"
    assert student["CasteCategory"] == "EWS"
    assert student["PhysicallyChallenged"] == "NO"
    assert student["Faculty"] == "SCIENCE"
    assert student["FullMarks"] == "500"
    assert student["TotalMarks"] == "465"
    assert student["Percentage"] == "93.00"


def test_bootstrap_student_data_reuses_cache_when_fresh(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "NSP_data"
    pdf_dir.mkdir()
    pdf_path = pdf_dir / "SCIENCE.pdf"
    pdf_path.write_bytes(b"not a real pdf")

    cache_path = tmp_path / "student_data_cache.pkl"
    student_record = {
        "RollCode": "99999",
        "RollNumber": "00000001",
        "Year": "2099",
        "StudentName": "TEST STUDENT",
        "DOB": "01-01-2000",
        "FatherName": "TEST FATHER",
        "Gender": "Female",
        "CasteCategory": "EWS",
        "PhysicallyChallenged": "NO",
        "Faculty": "SCIENCE",
        "FullMarks": "500",
        "TotalMarks": "465",
        "Percentage": "93.00",
    }
    with open(cache_path, "wb") as f:
        pickle.dump({"99999_00000001": student_record}, f)

    monkeypatch.setattr("bot.BASE_DIR", str(tmp_path))
    monkeypatch.setattr("bot.CACHE_FILE", str(cache_path))
    monkeypatch.setattr("bot.get_default_pdf_folder", lambda: str(pdf_dir))
    monkeypatch.setattr("bot.extract_pdf_data", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("PDF parsing should not run when cache is fresh")))

    result = bootstrap_student_data(str(pdf_dir))

    assert result is True
    assert "99999_00000001" in bot.STUDENT_DATA


def test_cache_freshness_uses_requested_pdf_folder(tmp_path, monkeypatch):
    default_pdf_dir = tmp_path / "default"
    requested_pdf_dir = tmp_path / "requested"
    default_pdf_dir.mkdir()
    requested_pdf_dir.mkdir()
    requested_pdf = requested_pdf_dir / "SCIENCE.pdf"
    requested_pdf.write_bytes(b"pdf")

    cache_path = tmp_path / "cache.pkl"
    cache_path.write_bytes(b"cache")
    os.utime(cache_path, (100, 100))
    os.utime(requested_pdf, (200, 200))

    monkeypatch.setattr(bot, "CACHE_FILE", str(cache_path))
    monkeypatch.setattr(bot, "get_default_pdf_folder", lambda: str(default_pdf_dir))

    assert bot.cache_is_stale(str(requested_pdf_dir)) is True


def test_verify_pdf_folder_accepts_uppercase_extension(tmp_path):
    (tmp_path / "SCIENCE.PDF").write_bytes(b"pdf")

    assert bot.verify_pdf_folder(str(tmp_path)) is True


def test_refresh_preserves_existing_cache_if_pdf_rebuild_fails(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache.pkl"
    cache_path.write_bytes(b"existing cache")
    monkeypatch.setattr(bot, "CACHE_FILE", str(cache_path))
    monkeypatch.setattr(bot, "extract_pdf_data", lambda _folder: False)

    assert bot.refresh_student_data(str(tmp_path)) is False
    assert cache_path.read_bytes() == b"existing cache"


def test_student_details_escape_html_in_record_fields(monkeypatch):
    class Message:
        def __init__(self):
            self.text = "00000001"
            self.reply_text = AsyncMock()

    student = {
        "RollCode": "99999",
        "RollNumber": "00000001",
        "Year": "2099",
        "StudentName": "A <b>B</b> & C",
        "DOB": "01-01-2000",
        "FatherName": "TEST FATHER",
        "Gender": "Female",
        "CasteCategory": "EWS",
        "PhysicallyChallenged": "NO",
        "Faculty": "SCIENCE",
        "FullMarks": "500",
        "TotalMarks": "465",
        "Percentage": "93.00",
    }

    async def allow_access(_update, _context):
        return True

    message = Message()
    context = SimpleNamespace(user_data={"step": 2, "roll_code": "99999"})
    update = SimpleNamespace(message=message)
    monkeypatch.setattr(bot, "STUDENT_DATA", {"99999_00000001": student})
    monkeypatch.setattr(bot, "ensure_access", allow_access)

    asyncio.run(bot.handle_message(update, context))

    rendered_text = message.reply_text.call_args.args[0]
    assert "&lt;b&gt;B&lt;/b&gt; &amp; C" in rendered_text
    assert "Record found. This bot does not determine NSP eligibility." in rendered_text
    assert message.reply_text.call_args.kwargs["parse_mode"] == "HTML"


def test_invalid_roll_code_keeps_lookup_on_roll_code_step(monkeypatch):
    class Message:
        text = "12x"

        def __init__(self):
            self.reply_text = AsyncMock()

    async def allow_access(_update, _context):
        return True

    message = Message()
    context = SimpleNamespace(user_data={"step": 1})
    update = SimpleNamespace(message=message)
    monkeypatch.setattr(bot, "ensure_access", allow_access)

    asyncio.run(bot.handle_message(update, context))

    assert context.user_data["step"] == 1
    assert "digits only" in message.reply_text.call_args.args[0]
