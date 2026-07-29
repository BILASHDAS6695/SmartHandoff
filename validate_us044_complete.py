#!/usr/bin/env python3
"""
Validation script for US-044 implementation.

Verifies all requirements from task files are met:
- All production files exist
- All test files exist  
- All configuration files exist
- Code compiles without syntax errors
- YAML files are valid
- Test methods are present

Usage:
    python validate_us044_complete.py
"""
import ast
import pathlib
import sys
from typing import Dict, List, Tuple

import yaml


def validate_file_exists(path: str, description: str) -> Tuple[bool, str]:
    """Check if a file exists."""
    p = pathlib.Path(path)
    if p.exists():
        return True, f"✓ {description}: {path}"
    else:
        return False, f"✗ {description}: NOT FOUND — {path}"


def validate_python_syntax(path: str, description: str) -> Tuple[bool, str]:
    """Check Python syntax by parsing AST."""
    p = pathlib.Path(path)
    if not p.exists():
        return False, f"✗ {description}: File not found — {path}"
    
    try:
        ast.parse(p.read_text(), filename=str(p))
        return True, f"✓ {description}: Syntax OK"
    except SyntaxError as e:
        return False, f"✗ {description}: Syntax error — {e.msg} at line {e.lineno}"


def validate_yaml_file(path: str, description: str) -> Tuple[bool, str]:
    """Check YAML syntax."""
    p = pathlib.Path(path)
    if not p.exists():
        return False, f"✗ {description}: File not found — {path}"
    
    try:
        data = yaml.safe_load(p.read_text())
        keys = list(data.keys()) if isinstance(data, dict) else "list"
        return True, f"✓ {description}: Valid YAML, keys: {keys}"
    except yaml.YAMLError as e:
        return False, f"✗ {description}: YAML error — {e}"


def count_test_methods(path: str) -> int:
    """Count test methods in a Python file."""
    p = pathlib.Path(path)
    if not p.exists():
        return 0
    
    content = p.read_text()
    tree = ast.parse(content)
    
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith("test_"):
                count += 1
        elif isinstance(node, ast.AsyncFunctionDef):
            if node.name.startswith("test_"):
                count += 1
    
    return count


def validate_test_methods_present(path: str, min_expected: int, description: str) -> Tuple[bool, str]:
    """Check that test file has expected number of test methods."""
    p = pathlib.Path(path)
    if not p.exists():
        return False, f"✗ {description}: File not found — {path}"
    
    count = count_test_methods(path)
    if count >= min_expected:
        return True, f"✓ {description}: {count} test methods (expected ≥{min_expected})"
    else:
        return False, f"✗ {description}: Only {count} test methods (expected ≥{min_expected})"


def validate_import_statement(path: str, import_str: str, description: str) -> Tuple[bool, str]:
    """Check if a specific import statement exists in a file."""
    p = pathlib.Path(path)
    if not p.exists():
        return False, f"✗ {description}: File not found — {path}"
    
    content = p.read_text()
    if import_str in content:
        return True, f"✓ {description}: Found '{import_str}'"
    else:
        return False, f"✗ {description}: Missing '{import_str}'"


def main() -> int:
    """Run all validation checks."""
    print("\n" + "=" * 80)
    print("US-044 IMPLEMENTATION VALIDATION")
    print("=" * 80 + "\n")
    
    all_passed = True
    checks: List[Tuple[bool, str]] = []
    
    # Production code files
    print("PRODUCTION CODE FILES")
    print("-" * 80)
    prod_files = [
        ("backend/app/agents/patient_comm/urgency/__init__.py", "Module init"),
        ("backend/app/agents/patient_comm/urgency/schemas.py", "Pydantic schemas"),
        ("backend/app/agents/patient_comm/urgency/config_loader.py", "Config loader"),
        ("backend/app/agents/patient_comm/urgency/keyword_matcher.py", "Phase 1 keyword matcher"),
        ("backend/app/agents/patient_comm/urgency/semantic_classifier.py", "Phase 2 semantic classifier"),
        ("backend/app/agents/patient_comm/urgency/detector.py", "UrgencyDetector facade"),
        ("backend/app/agents/patient_comm/urgency/emergency_handler.py", "Emergency alert handler"),
    ]
    
    for filepath, description in prod_files:
        status, msg = validate_file_exists(filepath, description)
        checks.append((status, msg))
        all_passed = all_passed and status
        print(msg)
    
    # Python syntax validation
    print("\nPYTHON SYNTAX VALIDATION")
    print("-" * 80)
    syntax_files = [
        ("backend/app/agents/patient_comm/urgency/schemas.py", "schemas.py syntax"),
        ("backend/app/agents/patient_comm/urgency/config_loader.py", "config_loader.py syntax"),
        ("backend/app/agents/patient_comm/urgency/keyword_matcher.py", "keyword_matcher.py syntax"),
        ("backend/app/agents/patient_comm/urgency/semantic_classifier.py", "semantic_classifier.py syntax"),
        ("backend/app/agents/patient_comm/urgency/detector.py", "detector.py syntax"),
        ("backend/app/agents/patient_comm/urgency/emergency_handler.py", "emergency_handler.py syntax"),
    ]
    
    for filepath, description in syntax_files:
        status, msg = validate_python_syntax(filepath, description)
        checks.append((status, msg))
        all_passed = all_passed and status
        print(msg)
    
    # Configuration files
    print("\nCONFIGURATION FILES")
    print("-" * 80)
    config_files = [
        ("config/urgency_keywords.yaml", "Urgency keywords config"),
        ("config/emergency_contacts.yaml", "Emergency contacts config"),
    ]
    
    for filepath, description in config_files:
        status, msg = validate_yaml_file(filepath, description)
        checks.append((status, msg))
        all_passed = all_passed and status
        print(msg)
    
    # Test files
    print("\nTEST FILES")
    print("-" * 80)
    test_files = [
        ("backend/tests/unit/agents/patient_comm/urgency/__init__.py", "Test package init"),
        ("backend/tests/unit/agents/patient_comm/urgency/test_keyword_matcher.py", "Keyword matcher tests"),
        ("backend/tests/unit/agents/patient_comm/urgency/test_semantic_classifier.py", "Semantic classifier tests"),
        ("backend/tests/unit/agents/patient_comm/urgency/test_urgency_detector.py", "Urgency detector tests"),
        ("backend/tests/unit/agents/patient_comm/urgency/test_emergency_handler.py", "Emergency handler tests (NEWLY CREATED)"),
        ("services/api-gateway/tests/unit/routers/test_chat_urgency_integration.py", "Pipeline integration tests"),
    ]
    
    for filepath, description in test_files:
        status, msg = validate_file_exists(filepath, description)
        checks.append((status, msg))
        all_passed = all_passed and status
        print(msg)
    
    # Test method counts
    print("\nTEST METHOD COUNTS")
    print("-" * 80)
    test_method_counts = [
        ("backend/tests/unit/agents/patient_comm/urgency/test_keyword_matcher.py", 10, "Keyword matcher tests"),
        ("backend/tests/unit/agents/patient_comm/urgency/test_semantic_classifier.py", 8, "Semantic classifier tests"),
        ("backend/tests/unit/agents/patient_comm/urgency/test_urgency_detector.py", 4, "Urgency detector tests"),
        ("backend/tests/unit/agents/patient_comm/urgency/test_emergency_handler.py", 10, "Emergency handler tests"),
        ("services/api-gateway/tests/unit/routers/test_chat_urgency_integration.py", 2, "Pipeline integration tests"),
    ]
    
    total_tests = 0
    for filepath, min_expected, description in test_method_counts:
        status, msg = validate_test_methods_present(filepath, min_expected, description)
        checks.append((status, msg))
        all_passed = all_passed and status
        print(msg)
        
        if status:
            count = count_test_methods(filepath)
            total_tests += count
    
    print(f"\n  ➜ TOTAL TEST METHODS: {total_tests} (requirement: ≥30)")
    if total_tests >= 30:
        print("    ✓ Test count requirement met")
    else:
        print(f"    ✗ Test count below requirement (have {total_tests}, need ≥30)")
        all_passed = False
    
    # Pipeline integration checks
    print("\nPIPELINE INTEGRATION")
    print("-" * 80)
    chat_imports = [
        ("services/api-gateway/app/routers/chat.py", "from backend.app.agents.patient_comm.urgency.detector import UrgencyDetector", "UrgencyDetector import"),
        ("services/api-gateway/app/routers/chat.py", "from backend.app.agents.patient_comm.urgency.emergency_handler import EmergencyAlertHandler", "EmergencyAlertHandler import"),
        ("services/api-gateway/app/routers/chat.py", "_urgency_detector = UrgencyDetector()", "Urgency detector singleton"),
        ("services/api-gateway/app/routers/chat.py", "_emergency_handler = EmergencyAlertHandler()", "Emergency handler singleton"),
        ("services/api-gateway/app/routers/chat.py", "_get_patient_first_name", "Patient name helper function"),
    ]
    
    for filepath, import_str, description in chat_imports:
        status, msg = validate_import_statement(filepath, import_str, description)
        checks.append((status, msg))
        all_passed = all_passed and status
        print(msg)
    
    # Database migration
    print("\nDATABASE MIGRATION")
    print("-" * 80)
    status, msg = validate_file_exists(
        "backend/alembic/versions/h2e5c8d91f36_add_urgency_flag_to_chatbot_transcript.py",
        "Alembic migration"
    )
    checks.append((status, msg))
    all_passed = all_passed and status
    print(msg)
    
    # Summary
    print("\n" + "=" * 80)
    passed_count = sum(1 for status, _ in checks if status)
    total_count = len(checks)
    print(f"VALIDATION SUMMARY: {passed_count}/{total_count} checks passed")
    print("=" * 80 + "\n")
    
    if all_passed:
        print("✅ ALL VALIDATION CHECKS PASSED")
        print("\nUS-044 implementation is complete and ready for code review.")
        print("\nNext steps:")
        print("  1. Run unit tests: pytest backend/tests/unit/agents/patient_comm/urgency/ ...")
        print("  2. Review code with Security Engineer (PHI protection)")
        print("  3. Review with AI/ML Engineer (model/threshold)")
        print("  4. Review with Backend Engineer (pipeline/DB)")
        print("  5. Merge to main and deploy")
        return 0
    else:
        print("❌ VALIDATION FAILED - SEE ERRORS ABOVE")
        print("\nPlease fix the issues listed above before proceeding.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
