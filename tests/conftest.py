"""
Shared pytest fixtures and configuration for the Eightfold Transformer test suite.
"""

import sys
import os

# Ensure the project root is on sys.path so all imports work when running
# pytest from any directory inside the project.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
