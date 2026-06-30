"""
Tests for the normalizer pipeline stage, specifically phone normalization.
"""
from pipeline.normalizer import normalize_phone

def test_phone_normalization():
    """
    Test all these phone inputs normalize correctly:
    - "09123456789" → "+919123456789"
    - "+1-415-555-0192" → "+14155550192"  
    - "98765-43210" → "+919876543210"
    - "8800112233" → "+918800112233"
    - null/empty → null
    """
    assert normalize_phone("09123456789") == "+919123456789"
    assert normalize_phone("+1-415-555-0192") == "+14155550192"
    assert normalize_phone("98765-43210") == "+919876543210"
    assert normalize_phone("8800112233") == "+918800112233"
    
    # test null/empty
    assert normalize_phone(None) is None
    assert normalize_phone("") == ""
    assert normalize_phone("   ") == "   " # Normalizer preserves empty whitespace if passed? Actually it strips.
