"""A small data-only skill language. There is no generated JavaScript execution."""

import hashlib
import json
import re


class SkillError(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(skill):
    if not isinstance(skill, dict) or skill.get("schema") != "once-actions/v1":
        raise SkillError("Unsupported skill format")
    if set(skill) != {"schema", "name", "parameters", "steps", "hash"}:
        raise SkillError("Unexpected skill fields")
    if skill["hash"] != fingerprint({k: v for k, v in skill.items() if k != "hash"}):
        raise SkillError("The skill changed after compilation")
    if not isinstance(skill["name"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", skill["name"]):
        raise SkillError("Use a short snake_case skill name")
    parameters = skill["parameters"]
    if not isinstance(parameters, list) or not 1 <= len(parameters) <= 20:
        raise SkillError("A skill needs 1–20 named parameters")
    if any(not isinstance(k, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", k) for k in parameters):
        raise SkillError("Invalid parameter name")
    if len(set(parameters)) != len(parameters):
        raise SkillError("Duplicate parameter names")
    if not isinstance(skill["steps"], list) or not 1 <= len(skill["steps"]) <= 100:
        raise SkillError("A skill needs 1–100 demonstrated steps")
    for step in skill["steps"]:
        if not isinstance(step, dict) or step.get("action") not in ("fill", "select", "click"):
            raise SkillError("Unsupported step")
        expected = {"action", "target"} | ({"parameter"} if step["action"] != "click" else set())
        if set(step) != expected:
            raise SkillError("Steps may contain named parameters, never literal input values or code")
        target = step["target"]
        if not isinstance(target, dict) or set(target) not in ({"role", "name"}, {"role", "name", "group"}):
            raise SkillError("Invalid semantic target")
        roles = {"fill": {"textbox", "spinbutton"}, "select": {"combobox"}, "click": {"button"}}
        if not isinstance(target["role"], str) or target["role"] not in roles[step["action"]]:
            raise SkillError("Target role does not support that action")
        for field in ("name", "group"):
            if field in target and (not isinstance(target[field], str) or not 1 <= len(target[field]) <= 160):
                raise SkillError("A target needs a short accessible name")
        if step["action"] != "click" and step["parameter"] not in parameters:
            raise SkillError("Step references an unknown parameter")
    return skill


def compile_skill(name, parameters, steps):
    skill = {"schema": "once-actions/v1", "name": name, "parameters": parameters, "steps": steps}
    skill["hash"] = fingerprint(skill)
    return validate(skill)


def tool_schema(skill):
    validate(skill)
    return {
        "type": "function",
        "name": skill["name"],
        "description": "Execute the user-demonstrated browser workflow. May require correction; "
        "does not infer permission to use other websites.",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {name: {"type": "string"} for name in skill["parameters"]},
            "required": skill["parameters"],
            "additionalProperties": False,
        },
    }
