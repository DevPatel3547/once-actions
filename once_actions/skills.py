"""A small data-only skill language. There is no generated JavaScript execution."""

import hashlib
import json
import re


class SkillError(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(skill):
    if not isinstance(skill, dict) or skill.get("schema") not in ("once-actions/v1", "once-actions/v2"):
        raise SkillError("Unsupported skill format")
    version2 = skill["schema"] == "once-actions/v2"
    fields = {"schema", "name", "parameters", "steps", "hash"}
    if version2:
        fields |= {"start_url", "success"}
    if set(skill) != fields:
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
        actions = (
            ("fill", "select", "click", "press", "check", "uncheck")
            if version2
            else ("fill", "select", "click")
        )
        if not isinstance(step, dict) or step.get("action") not in actions:
            raise SkillError("Unsupported step")
        expected = {"action", "target"}
        if step["action"] in ("fill", "select"):
            expected.add("parameter")
        if step["action"] == "press":
            expected.add("key")
            if step.get("key") != "Enter":
                raise SkillError("Only demonstrated Enter presses are supported")
        if set(step) != expected:
            raise SkillError("Steps may contain named parameters, never literal input values or code")
        target = step["target"]
        validate_target(target, step["action"], version2)
        if step["action"] in ("fill", "select") and step["parameter"] not in parameters:
            raise SkillError("Step references an unknown parameter")
    if version2:
        from .scope import application_origin

        application_origin(skill["start_url"])
        success = skill["success"]
        if not isinstance(success, dict) or set(success) != {"kind", "value"}:
            raise SkillError("Choose a visible-text outcome check")
        if success["kind"] not in ("text", "parameter"):
            raise SkillError("Unsupported outcome check")
        if not isinstance(success["value"], str) or not 1 <= len(success["value"]) <= 2000:
            raise SkillError("Outcome text is required")
        if success["kind"] == "parameter" and success["value"] not in parameters:
            raise SkillError("Outcome references an unknown parameter")
    return skill


def validate_target(target, action, version2=True):
    allowed = ({"role", "name"}, {"role", "name", "group"})
    if version2:
        allowed += ({"placeholder"}, {"placeholder", "group"})
    if not isinstance(target, dict) or set(target) not in allowed:
        raise SkillError("Invalid semantic target")
    roles = {
        "fill": ("textbox", "spinbutton"),
        "select": ("combobox",),
        "click": ("button", "link") if version2 else ("button",),
        "press": ("textbox", "spinbutton"),
        "check": ("checkbox",),
        "uncheck": ("checkbox",),
    }
    if "placeholder" in target:
        if action not in ("fill", "press"):
            raise SkillError("Placeholders only identify text inputs")
    elif target["role"] not in roles[action]:
        raise SkillError("Target role does not support that action")
    for field in ("name", "group", "placeholder"):
        if field in target and (not isinstance(target[field], str) or not 1 <= len(target[field]) <= 160):
            raise SkillError("A target needs a short accessible name or placeholder")


def compile_skill(name, parameters, steps):
    skill = {"schema": "once-actions/v1", "name": name, "parameters": parameters, "steps": steps}
    skill["hash"] = fingerprint(skill)
    return validate(skill)


def compile_workflow(name, parameters, steps, start_url, success):
    skill = {
        "schema": "once-actions/v2",
        "name": name,
        "parameters": parameters,
        "steps": steps,
        "start_url": start_url,
        "success": success,
    }
    skill["hash"] = fingerprint(skill)
    return validate(skill)


def correct_target(skill, index, target):
    """A reviewed correction changes only one target, never actions or scope."""
    validate(skill)
    if type(index) is not int or not 0 <= index < len(skill["steps"]):
        raise SkillError("Choose an existing step")
    corrected = json.loads(json.dumps(skill))
    corrected["steps"][index]["target"] = target
    corrected["hash"] = fingerprint({k: v for k, v in corrected.items() if k != "hash"})
    return validate(corrected)


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
