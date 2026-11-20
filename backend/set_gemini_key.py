"""Saves a Gemini API key for the Flo-Wing Assistant (chatbot) and checks that it works.

Run:  python set_gemini_key.py          (or double-click "SET GEMINI KEY.bat" in the project folder)

What it does:
  1. asks for the key (paste it, then press Enter),
  2. sends Google one tiny test question to check the key and the model,
  3. writes GEMINI_API_KEY into backend/.env (other settings in that file are kept).
The key is only stored in backend/.env on this computer. Never share or upload that file.
"""
from __future__ import annotations

import os
import re
import sys
from getpass import getpass

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, ".env")
EXAMPLE = os.path.join(HERE, ".env.example")
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS = ["gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite", "gemini-flash-latest"]


def read_env(path: str) -> list[str]:
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()
    return []


def set_values(lines: list[str], values: dict[str, str]) -> list[str]:
    out, done = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            out.append(f"{key}={values[key]}")
            done.add(key)
        else:
            out.append(line)
    for k, v in values.items():
        if k not in done:
            out.append(f"{k}={v}")
    return out


def test_key(key: str) -> tuple[str | None, str]:
    """Returns (working model or None, message)."""
    try:
        import requests
    except ImportError:
        return None, "The 'requests' package is missing. Start the dashboard once (it installs it), then run this again."
    last = ""
    for model in MODELS:
        try:
            r = requests.post(API.format(model=model), timeout=20,
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json={"contents": [{"role": "user", "parts": [{"text": "Reply with the word OK."}]}],
                                    "generationConfig": {"maxOutputTokens": 5, "temperature": 0}})
        except Exception as e:  # noqa: BLE001
            return None, f"Could not reach Google ({type(e).__name__}). Check the internet connection."
        if r.status_code == 200:
            return model, "ok"
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = r.text[:200]
        if r.status_code in (400, 401, 403) and re.search(r"api key|API_KEY|permission|invalid", msg, re.I):
            return None, f"Google rejected this key: {msg}"
        if r.status_code == 429:
            return model, "The key works, but Google says the free limit is used up for now. It will work again later."
        last = f"{r.status_code}: {msg}"          # model not available for this key: try the next one
    return None, f"No Gemini model answered ({last})."


def main() -> int:
    print()
    print("  ===== Flo-Wing Assistant: Gemini key =====")
    print()
    print("  Get a key at https://aistudio.google.com/apikey  (Create API key, then Copy).")
    print("  Paste it below and press Enter. For safety the key is not shown while you paste.")
    print()
    key = getpass("  Gemini API key: ").strip().strip('"').strip("'")
    if not key:
        print("\n  No key entered. Nothing was changed.")
        return 1
    if " " in key or len(key) < 20:
        print("\n  That doesn't look like a Gemini key (it is one long word, usually starting with AIza).")
        return 1
    if not key.startswith("AIza"):
        print("  Note: Gemini keys usually start with 'AIza'. Checking it anyway...")

    print("\n  Checking the key with Google...")
    model, msg = test_key(key)
    if model is None:
        print(f"\n  [X] {msg}\n  The key was NOT saved.")
        return 1
    print(f"  [OK] Key works (model: {model})." if msg == "ok" else f"  [!] {msg}")

    lines = read_env(ENV) or read_env(EXAMPLE)
    lines = set_values(lines, {"GEMINI_API_KEY": key, "GEMINI_MODEL": model, "ASSISTANT_GEMINI": "on"})
    with open(ENV, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    print(f"\n  Saved to {ENV}")
    print("\n  Next: close the two black dashboard windows and double-click START DASHBOARD.bat again.")
    print("  Then open http://localhost:8000/api/health - it should say \"assistant\": \"rules + gemini\".")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        code = 1
    if os.name == "nt":
        input("\n  Press Enter to close...")
    sys.exit(code)
