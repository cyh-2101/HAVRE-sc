from __future__ import annotations

import sys
import unittest
from pathlib import Path

from mcp import Client, StdioServerParameters

from services.mcp_companion.server import create_server


ROOT = Path(__file__).resolve().parents[1]


class ChatGptMcpCompanionTests(unittest.IsolatedAsyncioTestCase):
    async def test_in_process_server_is_read_only_and_public_identity_only(self) -> None:
        async with Client(create_server()) as client:
            self.assertIn("warm toward emotion", client.instructions or "")
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            self.assertEqual(
                set(tools), {"havre_companion_profile", "havre_plan_reply"}
            )
            for tool in tools.values():
                self.assertTrue(tool.annotations.read_only_hint)
                self.assertFalse(tool.annotations.destructive_hint)
                self.assertFalse(tool.annotations.open_world_hint)

            result = await client.call_tool("havre_companion_profile")
            self.assertFalse(result.is_error)
            profile = result.structured_content
            assert profile is not None
            self.assertEqual(profile["identity_version"], "identity-v1")
            self.assertIn("warm without becoming indulgent", profile["identity"])
            self.assertFalse(profile["privacy"]["private_havre_history_attached"])
            self.assertFalse(profile["privacy"]["durable_write_performed"])
            self.assertFalse(profile["privacy"]["oa70_used"])

    async def test_turn_plan_preserves_multiple_requests_without_attaching_history(self) -> None:
        async with Client(create_server()) as client:
            result = await client.call_tool(
                "havre_plan_reply",
                {
                    "message": (
                        "先告诉我为什么体感差，再比较两个方案，最后给我一个明确建议。"
                    )
                },
            )
            self.assertFalse(result.is_error)
            plan = result.structured_content
            assert plan is not None
            self.assertEqual(len(plan["must_address"]), 3)
            self.assertEqual(plan["decision_requirement"], "recommend_one")
            self.assertFalse(plan["havre_history_attached"])
            self.assertIn("Explicit tasks/detail requests still need complete answers", plan["response_instruction"])

    async def test_prior_context_is_detected_but_never_fabricated_or_loaded(self) -> None:
        async with Client(create_server()) as client:
            result = await client.call_tool(
                "havre_plan_reply",
                {"message": "继续我们上次讨论的那个方案。"},
            )
            plan = result.structured_content
            assert plan is not None
            self.assertEqual(plan["memory_need_detected"], "required")
            self.assertFalse(plan["havre_history_attached"])
            self.assertIn("ask one concise clarifying question", plan["response_instruction"])

    async def test_real_stdio_transport_initializes_and_calls_tool(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "services.mcp_companion.server"],
            cwd=str(ROOT),
        )
        async with Client(params, read_timeout_seconds=20) as client:
            listed = await client.list_tools()
            self.assertIn("havre_plan_reply", {tool.name for tool in listed.tools})
            result = await client.call_tool(
                "havre_plan_reply", {"message": "今天很累，不想听解决方案。"}
            )
            self.assertFalse(result.is_error)
            assert result.structured_content is not None
            self.assertEqual(result.structured_content["mode"], "talk")


if __name__ == "__main__":
    unittest.main()
