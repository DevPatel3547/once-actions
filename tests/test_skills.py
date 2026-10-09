import copy
import unittest

from once_actions.runner import local_origin
from once_actions.skills import SkillError, compile_skill, fingerprint, tool_schema, validate


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.skill = compile_skill(
            "enter_name",
            ["customer"],
            [{"action": "fill", "target": {"role": "textbox", "name": "Customer"}, "parameter": "customer"}],
        )

    def test_portable_tool_contract(self):
        schema = tool_schema(self.skill)
        self.assertTrue(schema["strict"])
        self.assertFalse(schema["parameters"]["additionalProperties"])
        self.assertEqual(schema["parameters"]["required"], ["customer"])

    def test_tampering_requires_recompilation(self):
        self.skill["steps"][0]["target"]["name"] = "Something else"
        with self.assertRaises(SkillError):
            validate(self.skill)

    def test_rejects_literals_code_and_malformed_targets(self):
        for replacement in (
            {"action": "evaluate", "code": "fetch('/destroy')"},
            {"action": "fill", "target": {"role": "textbox", "name": "Customer"}, "value": "secret"},
            {"action": [], "target": {}},
            {"action": "click", "target": {"role": [], "name": "Save"}},
            {"action": "click", "target": {"role": "button", "name": "Save", "selector": "#save"}},
        ):
            with self.subTest(replacement=replacement), self.assertRaises(SkillError):
                compile_skill("invalid", ["customer"], [replacement])

    def test_unknown_parameters_rejected_even_with_valid_hash(self):
        skill = copy.deepcopy(self.skill)
        skill["steps"][0]["parameter"] = "missing"
        skill["hash"] = fingerprint({k: v for k, v in skill.items() if k != "hash"})
        with self.assertRaises(SkillError):
            validate(skill)

    def test_external_targets_rejected(self):
        for url in (
            "https://example.com",
            "http://example.com:80",
            "http://localhost:8780",
            "http://127.0.0.1",
            "http://user:password@127.0.0.1:8780",
            "http://127.0.0.1:8780/#x",
        ):
            with self.subTest(url=url), self.assertRaises(SkillError):
                local_origin(url)
        self.assertEqual(local_origin("http://127.0.0.1:8780/app"), "http://127.0.0.1:8780")
