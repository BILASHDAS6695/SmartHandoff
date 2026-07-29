"""US-044: Urgency Detector — Patient Communication Agent.

Patient safety critical feature that detects urgent medical symptoms in chat
and displays emergency guidance within 10 seconds.

Modules:
    - schemas: Pydantic models for detection result, Gemini output, config
    - config_loader: Load and cache urgency keywords and emergency contacts
    - keyword_matcher: Phase 1 fast keyword pattern matching (US-044 TASK-002)
    - semantic_classifier: Phase 2 Gemini semantic classification (US-044 TASK-003)
    - detector: UrgencyDetector facade orchestrating both phases (US-044 TASK-003)
    - emergency_handler: Hardcoded reply, Pub/Sub publish, DB write (US-044 TASK-004)
"""
