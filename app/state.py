"""
Shared in-memory state for pending Slack approvals.
In production, this should be replaced with a persistent store (Redis, SQLite, etc.)
"""
from typing import Dict, Any

# Key: Slack message timestamp (ts), Value: dict with lead info, draft, and channel
pending_approvals: Dict[str, Dict[str, Any]] = {}
