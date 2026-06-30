"""
Tests for the merger pipeline stage.
"""
from pipeline.extractor import extract
from pipeline.normalizer import normalize
from pipeline.merger import merge_all

def test_merger_aarav_mehta():
    """
    Test: Aarav Mehta appears in CSV with name "Aarav Mehta" and in TXT notes also as
    "Aarav Mehta" but phone differs. Both should normalize to +919876543210.
    Merger should produce exactly ONE record.
    """
    csv_raw = {
        "source_name": "csv",
        "raw_data": {
            "full_name": "Aarav Mehta",
            "emails": ["aarav.mehta@gmail.com"],
            "phones": ["9876543210"]
        }
    }
    
    txt_raw = {
        "source_name": "txt",
        "raw_data": {
            "full_name": "Aarav Mehta",
            "emails": ["aarav.mehta@gmail.com"],
            "phones": ["98765-43210"]
        }
    }

    # Extract and normalize
    canonical_csv = normalize(extract(csv_raw))
    canonical_txt = normalize(extract(txt_raw))

    # Merge
    merged_records = merge_all([canonical_csv, canonical_txt])

    # Assert exactly ONE record is produced
    assert len(merged_records) == 1
    
    record = merged_records[0]
    
    # Assert name and unified email
    assert record["full_name"] == "Aarav Mehta"
    assert record["emails"] == ["aarav.mehta@gmail.com"]
    
    # Assert phone normalized correctly
    assert record["phones"] == ["+919876543210"]
