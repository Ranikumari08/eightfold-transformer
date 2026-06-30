"""
Tests for graceful failure handling across sources and the pipeline.
"""
import os
import json
from sources.github_source import read_github_source
from sources.csv_source import read_csv_source
from sources.ats_json_source import read_ats_json_source
from pipeline.extractor import extract

def test_github_source_404():
    """
    Test that pipeline does NOT crash when GitHub username doesn't exist (API 404).
    Should return None.
    """
    result = read_github_source("this_user_definitely_does_not_exist_1234567890")
    assert result is None

def test_csv_wrong_path():
    """
    Test that pipeline does NOT crash when CSV file path is wrong.
    Should return an empty list.
    """
    result = read_csv_source("nonexistent_path/fake.csv")
    assert result == []

def test_ats_json_malformed(tmp_path):
    """
    Test that pipeline does NOT crash when ATS JSON is malformed/empty.
    Should return an empty list.
    """
    bad_file = tmp_path / "malformed.json"
    bad_file.write_text("{ this is not valid json }")
    
    result = read_ats_json_source(str(bad_file))
    assert result == []

def test_candidate_no_phone():
    """
    Test that pipeline does NOT crash when a candidate has no phone number at all.
    Should return null (None) for the phone field.
    """
    raw_record = {
        "source_name": "csv",
        "raw_data": {
            "name": "Jane Doe",
            "phone": None
        }
    }
    
    canonical = extract(raw_record)
    
    # phones should be None
    assert canonical["phones"] is None
