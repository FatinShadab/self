"""Small, optional voice helpers for the terminal UI.

Voice is deliberately best-effort: the TUI still works when no speech
backend or microphone is available.  Windows uses the built-in PowerShell
speech APIs; Linux can use an installed ``espeak``/``spd-say`` command.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading


class VoiceController:
    """Detect and use local speech backends without making them required."""

    def __init__(self) -> None:
        self.enabled = os.getenv("SELF_VOICE_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
        self._powershell = shutil.which("powershell") or shutil.which("pwsh")
        self._tts = self._detect_tts()
        self._speaking = threading.Lock()

    def _detect_tts(self) -> str | None:
        if self._powershell:
            return "powershell"
        for command in ("espeak-ng", "espeak", "spd-say"):
            if shutil.which(command):
                return command
        return None

    @property
    def output_available(self) -> bool:
        return self._tts is not None

    @property
    def input_available(self) -> bool:
        # System.Speech.Recognition is available on Windows desktop installs.
        # Docker/Linux intentionally reports this as unavailable unless a
        # future dedicated microphone backend is added.
        return os.name == "nt" and self._powershell is not None

    def status_text(self) -> str:
        output = "available" if self.output_available else "unavailable"
        input_status = "available" if self.input_available else "unavailable"
        state = "on" if self.enabled else "off"
        return f"Voice: {state} (output {output}, input {input_status})"

    def set_enabled(self, enabled: bool) -> str:
        self.enabled = enabled
        if enabled and not self.output_available:
            return "Voice output is unavailable on this host. Install espeak or use a Windows speech backend."
        return f"Voice output {'enabled' if enabled else 'disabled'}."

    def speak(self, text: str) -> bool:
        """Speak in the background, returning False when voice is unavailable."""
        if not self.enabled or not self.output_available or not text.strip():
            return False
        # Do not let a long narration backlog turn into a delayed speech queue.
        if not self._speaking.acquire(blocking=False):
            return False
        threading.Thread(target=self._speak_sync, args=(text[:2_000],), daemon=True).start()
        return True

    def _speak_sync(self, text: str) -> None:
        try:
            if self._tts == "powershell":
                script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$t = [Console]::In.ReadToEnd(); $s.Speak($t)"
                )
                process = subprocess.Popen(
                    [self._powershell or "powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                process.communicate(text, timeout=120)
            elif self._tts == "spd-say":
                subprocess.run([self._tts, "--", text], check=False, timeout=120, capture_output=True)
            else:
                subprocess.run([self._tts or "espeak", "-s", "165", text], check=False, timeout=120, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            self._speaking.release()

    def listen(self, timeout: int = 8) -> tuple[str | None, str | None]:
        """Capture one dictation phrase with Windows' default microphone."""
        if not self.input_available:
            return None, "Microphone input is unavailable in this environment."
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$r = New-Object System.Speech.Recognition.SpeechRecognitionEngine; "
            "$r.SetInputToDefaultAudioDevice(); "
            "$r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)); "
            "$x = $r.Recognize(); if ($null -ne $x) { [Console]::Out.Write($x.Text) }"
        )
        try:
            result = subprocess.run(
                [self._powershell or "powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=max(1, timeout),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return None, f"Microphone capture failed: {type(exc).__name__}."
        text = result.stdout.strip()
        if result.returncode != 0 or not text:
            return None, "I could not understand a microphone phrase."
        return text, None
