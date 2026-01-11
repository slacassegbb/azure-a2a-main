"""
Tests for the NLP processor module
"""

import pytest
from mcp_server_servicenow.nlp import NLPProcessor


class TestNLPProcessor:
    """Test cases for the NLPProcessor class"""

    def test_parse_search_query(self):
        """Test parsing natural language search queries"""
        # Test basic search
        result = NLPProcessor.parse_search_query("find all incidents about email")
        assert result["table"] == "incident"
        assert "123TEXTQUERY321=email" in result["query"]

        # Test with different table
        result = NLPProcessor.parse_search_query("search for users related to admin")
        assert result["table"] == "sys_user"
        assert "123TEXTQUERY321=admin" in result["query"]

        # Test with priority
        result = NLPProcessor.parse_search_query("show me all incidents with high priority")
        assert result["table"] == "incident"
        assert "priority=1" in result["query"]

        # Test with state
        result = NLPProcessor.parse_search_query("find all incidents in progress")
        assert result["table"] == "incident"
        assert "state=2" in result["query"]

    def test_parse_update_command(self):
        """Test parsing natural language update commands"""
        # Test basic update
        record_number, updates = NLPProcessor.parse_update_command(
            "Update incident INC0010001 saying I'm working on it"
        )
        assert record_number == "INC0010001"
        assert updates.get("comments") == "I'm working on it"
        assert updates.get("state") == 2  # In Progress

        # Test with explicit state change
        record_number, updates = NLPProcessor.parse_update_command(
            "Close incident INC0010002 with resolution: fixed the issue"
        )
        assert record_number == "INC0010002"
        assert updates.get("state") == 7  # Closed
        assert updates.get("close_notes") == "fixed the issue"
        assert updates.get("close_code") == "Solved (Permanently)"

        # Test with work notes
        record_number, updates = NLPProcessor.parse_update_command(
            "Update incident INC0010003 with work note: internal troubleshooting steps"
        )
        assert record_number == "INC0010003"
        assert updates.get("work_notes") == "internal troubleshooting steps"

    def test_parse_script_update(self):
        """Test parsing script update commands"""
        # Test script include
        filename, script_type, _ = NLPProcessor.parse_script_update(
            "update @my_script.js, it's a script include"
        )
        assert filename == "my_script.js"
        assert script_type == "sys_script_include"

        # Test business rule
        filename, script_type, _ = NLPProcessor.parse_script_update(
            "update @validation.js, it's a business rule"
        )
        assert filename == "validation.js"
        assert script_type == "sys_script"

        # Test client script
        filename, script_type, _ = NLPProcessor.parse_script_update(
            "update @form_script.js, it's a client script"
        )
        assert filename == "form_script.js"
        assert script_type == "sys_script_client"
