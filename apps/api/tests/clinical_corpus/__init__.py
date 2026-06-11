"""Synthetic clinical corpus + ground truth for end-to-end extraction proof.

Each case is a realistic clinical document the system has never seen, paired
with the findings a correct extraction MUST surface. The harness
(tests/test_clinical_extraction.py) runs each through the real pipeline
(OCR → entity extraction) and asserts the ground truth is recovered — the
demonstration that there is real technology inside, not a mockup.
"""
