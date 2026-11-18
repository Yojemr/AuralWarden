import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "integrations/codex/auralwarden"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def load_checker():
    spec = importlib.util.spec_from_file_location("agent_skill_check", ROOT / "scripts/check-agent-skill.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_skill_matches_runtime_contract():
    result = load_checker().validate(ROOT)
    assert {"list_windows", "separate_audio", "restore_audio"} <= set(result["control_actions"])


def test_agent_skill_rejects_a_stale_version(tmp_path):
    shutil.copytree(SKILL, tmp_path / "integrations/codex/auralwarden")
    (tmp_path / "VERSION").write_text("999.0.0")
    with pytest.raises(AssertionError, match="VERSION"):
        load_checker().validate(tmp_path)


def test_skill_metadata_has_no_external_dependency_or_secret():
    import yaml
    metadata = yaml.safe_load((SKILL / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert metadata["policy"]["allow_implicit_invocation"] is True
    assert "$auralwarden" in metadata["interface"]["default_prompt"]
    assert "dependencies" not in metadata
    assert {path.name for path in SKILL.iterdir()} == {
        "SKILL.md", "agents", "scripts", "references", "capabilities.json"}


def ps(script, timeout=20):
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return json.loads(result.stdout.decode("utf-8-sig"))


@pytest.mark.skipif(os.name != "nt" or not POWERSHELL, reason="Windows PowerShell required")
def test_discovery_is_numeric_and_never_launches_a_program(tmp_path):
    for version in ("1.9.0", "1.10.0", "1.5.0"):
        folder = tmp_path / "outputs" / f"AuralWarden-{version}"
        folder.mkdir(parents=True)
        (folder / "AuralWarden.exe").write_bytes(b"not executable")
    helper = SKILL / "scripts/Invoke-AuralWarden.ps1"
    result = ps(f"function Get-Process {{ @() }}; & '{helper}' -ProjectRoot '{tmp_path}' -Action discover")
    assert "1.10.0" in result["selected"]
    assert not (tmp_path / "work").exists()


@pytest.mark.skipif(os.name != "nt" or not POWERSHELL, reason="Windows PowerShell required")
def test_active_version_has_priority_and_ambiguous_instances_fail_closed(tmp_path):
    helper = SKILL / "scripts/Invoke-AuralWarden.ps1"
    old = tmp_path / "outputs/AuralWarden-1.5.0/AuralWarden.exe"
    new = tmp_path / "outputs/AuralWarden-1.6.0/AuralWarden.exe"
    for path in (old, new):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not executable")
    result = ps(f"function Get-Process {{ [pscustomobject]@{{Path='{old}'}} }}; & '{helper}' -ProjectRoot '{tmp_path}'")
    assert result["selected"] == str(old)
    result = ps(f"function Get-Process {{ [pscustomobject]@{{Path='{old}'}}; [pscustomobject]@{{Path='{new}'}} }}; & '{helper}' -ProjectRoot '{tmp_path}'")
    assert result["ambiguous"] and not result["selected"]
    result = ps(f"function Get-Process {{ [pscustomobject]@{{Path='{old}'}}; [pscustomobject]@{{Path=$null}} }}; & '{helper}' -ProjectRoot '{tmp_path}'")
    assert result["ambiguous"] and not result["selected"]


@pytest.mark.skipif(os.name != "nt" or not POWERSHELL, reason="Windows PowerShell required")
@pytest.mark.parametrize("action", json.loads((SKILL / "capabilities.json").read_text())["control_actions"])
def test_helper_sends_supported_action_and_cleans_only_its_files(tmp_path, action):
    helper = SKILL / "scripts/Invoke-AuralWarden.ps1"
    exe = tmp_path / "AuralWarden.exe"
    exe.write_bytes(b"never launched")
    retained = tmp_path / "work/keep.txt"
    retained.parent.mkdir()
    retained.write_text("keep")
    actions = json.dumps(json.loads((SKILL / "capabilities.json").read_text())["control_actions"])
    parameters = {"set_source": "@{source='demo://isolated'}", "set_hotwords": "@{hotwords=@('ayuda')}",
                  "transcript": "@{limit=10}", "alerts": "@{limit=10}",
                  "list_windows": "@{application='chrome'}", "list_audio_devices": "@{kind='microphone'}",
                  "select_windows_source": "@{kind='application_audio';window_id='synthetic'}",
                  "configure_session": "@{options=@{diarization=$true}}",
                  "set_stop_timer": "@{duration_seconds=60}",
                  "separate_audio": "@{application='chrome';confirmed=$true}"}.get(action, "@{}")
    # The mock replaces only the child process boundary. Request serialization,
    # negotiation, response parsing and temporary-file cleanup run unchanged.
    script = f"""
    function Get-Process {{ @() }}
    function Start-Process {{
        param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru)
        $requestPath=$ArgumentList[1].Trim('"'); $responsePath=$ArgumentList[3].Trim('"')
        $request=Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json
        if($request.PSObject.Properties.Name -contains 'token') {{ throw 'Secret sent in request' }}
        @{{ok=$true; action=$request.action; actions=('{actions}' | ConvertFrom-Json)}} | ConvertTo-Json | Set-Content -LiteralPath $responsePath -Encoding UTF8
        $client=New-Object PSObject
        $client | Add-Member ScriptMethod WaitForExit {{ param($timeout) return $true }}
        return $client
    }}
    & '{helper}' -Executable '{exe}' -ProjectRoot '{tmp_path}' -WorkDirectory '{retained.parent}' -Action {action} -Parameters {parameters}
    """
    result = ps(script)
    assert result["ok"] and result["action"] == action
    assert list(retained.parent.iterdir()) == [retained]
    assert exe.read_bytes() == b"never launched"
