"""Check the maintained skill against the application's public control surface."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path


def validate(root: Path) -> dict:
    skill = root / "integrations/codex/auralwarden"
    manifest = json.loads((skill / "capabilities.json").read_text(encoding="utf-8"))
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert manifest["verified_app_version"] == version, "Update the agent skill for VERSION"
    controller = ast.parse((root / "src/auralwarden/ui/main_window.py").read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(controller) if isinstance(node, ast.FunctionDef)
                  and node.name == "handle_local_control")
    declarations = [kw.value for node in ast.walk(method) if isinstance(node, ast.Call)
                    for kw in node.keywords if kw.arg == "actions"]
    assert len(declarations) == 1, "Review the changed capability declaration"
    actions = ast.literal_eval(declarations[0])
    assert manifest["control_actions"] == actions, "Agent actions differ from runtime capabilities"
    schema = json.loads((root / "docs/agent-control.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["action"]["enum"] == actions, "Update the public control schema"
    helper = (skill / "scripts/Invoke-AuralWarden.ps1").read_text(encoding="utf-8")
    selectors = re.search(r"\[ValidateSet\((.*?)\)\]", helper, re.S)
    assert selectors is not None
    assert set(re.findall(r"'([^']+)'", selectors[1])) == {"discover", *actions}, "Update helper action selectors"
    declared_limits = [ast.literal_eval(kw.value) for node in ast.walk(method) if isinstance(node, ast.Call)
                       for kw in node.keywords if kw.arg == "limits"]
    assert declared_limits == [manifest["limits"]], "Update the skill's advertised limits"
    protocol = ast.parse((root / "src/auralwarden/local_control.py").read_text(encoding="utf-8"))
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in protocol.body
              if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
              and node.targets[0].id in {"CONTROL_PROTOCOL_VERSION", "TRANSPORT_PROTOCOL_VERSION"}}
    assert manifest["control_protocol_version"] == values["CONTROL_PROTOCOL_VERSION"]
    assert manifest["transport_protocol_version"] == values["TRANSPORT_PROTOCOL_VERSION"]
    cli = ast.parse((root / "src/auralwarden/cli.py").read_text(encoding="utf-8"))
    commands = [node.args[0].value for node in ast.walk(cli) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "add_parser"
                and node.args and isinstance(node.args[0], ast.Constant)]
    assert set(commands) == set(manifest["backend_commands"]), "Review new or removed backend commands"
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: auralwarden\n")
    for relative in ("agents/openai.yaml", "scripts/Invoke-AuralWarden.ps1", manifest["reference"],
                     "references/maintenance.md"):
        assert (skill / relative).is_file(), f"Missing skill resource: {relative}"
    return manifest


if __name__ == "__main__":
    data = validate(Path(__file__).resolve().parents[1])
    print(f"Agent skill matches AuralWarden {data['verified_app_version']}: "
          f"{len(data['control_actions'])} local actions, {len(data['backend_commands'])} backend commands.")
