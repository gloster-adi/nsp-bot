import os
import pickle

from bot import parse_student_line, bootstrap_student_data


def test_parse_student_line_science_record():
    line = "82061-26010004 2026 SIDDHI RANI 20-01-2008 LALAN JEE JHA FemaleEWS NO SCIENCE 500 465 93.00"
    student = parse_student_line(line, "SCIENCE")

    assert student is not None
    assert student["RollCode"] == "82061"
    assert student["RollNumber"] == "26010004"
    assert student["StudentName"] == "SIDDHI RANI"
    assert student["DOB"] == "20-01-2008"
    assert student["FatherName"] == "LALAN JEE JHA"
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
        "RollCode": "82061",
        "RollNumber": "26010004",
        "Year": "2026",
        "StudentName": "SIDDHI RANI",
        "DOB": "20-01-2008",
        "FatherName": "LALAN JEE JHA",
        "Gender": "Female",
        "CasteCategory": "EWS",
        "PhysicallyChallenged": "NO",
        "Faculty": "SCIENCE",
        "FullMarks": "500",
        "TotalMarks": "465",
        "Percentage": "93.00",
    }
    with open(cache_path, "wb") as f:
        pickle.dump({"82061_26010004": student_record}, f)

    monkeypatch.setattr("bot.BASE_DIR", str(tmp_path))
    monkeypatch.setattr("bot.CACHE_FILE", str(cache_path))
    monkeypatch.setattr("bot.get_default_pdf_folder", lambda: str(pdf_dir))
    monkeypatch.setattr("bot.extract_pdf_data", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("PDF parsing should not run when cache is fresh")))

    result = bootstrap_student_data(str(pdf_dir))

    assert result is True
    assert "82061_26010004" in __import__("bot").STUDENT_DATA
