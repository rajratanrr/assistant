"""
jarvis.py — Full Speech-to-Speech Jarvis with modern OpenAI API and personal API integration.

Features:
- Microphone input → Speech-to-Text
- Simple NLP routing (chat / API / notes / exit)
- TTS output using pyttsx3
- Calls personal API safely using environment variables
"""

import os
import json
import time
import threading
import traceback
import requests
import speech_recognition as sr
import pyttsx3
from openai import OpenAI

# ----------------- CONFIGURATION -----------------
# Modern OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Personal API integration (optional)
PERSONAL_API_URL = os.getenv("https://api.openai.com/v1", "")
PERSONAL_API_KEY = os.getenv("sk-...QEoA", "")

# TTS and STT settings
TTS_RATE = 170
PHRASE_TIME_LIMIT = 12
AMBIENT_ADJUST_SECONDS = 1.5
API_TIMEOUT = 8
# -------------------------------------------------

# Initialize recognizer and microphone
recognizer = sr.Recognizer()
microphone = sr.Microphone()

# Initialize TTS engine
tts_engine = pyttsx3.init()
tts_engine.setProperty("rate", TTS_RATE)

# ----------------- UTILITY FUNCTIONS -----------------
def speak(text, block=True):
    """Speak text using TTS."""
    if not text:
        return
    def _speak():
        try:
            tts_engine.say(text)
            tts_engine.runAndWait()
        except Exception as e:
            print("TTS error:", e)
    if block:
        _speak()
    else:
        t = threading.Thread(target=_speak, daemon=True)
        t.start()

def llm_reply(user_text: str) -> str:
    """Get a reply from modern OpenAI GPT API."""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are Jarvis, a helpful assistant."},
                {"role": "user", "content": user_text}
            ],
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"GPT error: {e}"

def extract_intent(text: str) -> str:
    """Simple intent router."""
    t = (text or "").lower()
    if any(k in t for k in ("exit", "quit", "stop", "bye", "goodbye")):
        return "exit"
    if any(k in t for k in ("note:", "take note", "remember")):
        return "note"
    if any(k in t for k in ("get info", "status", "fetch", "call api", "my api")):
        return "call_api"
    return "chat"

def call_personal_api(user_text: str) -> dict:
    """Call personal API safely using environment variables."""
    if not PERSONAL_API_URL:
        return {"error": "Personal API URL not configured."}

    headers = {"Content-Type": "application/json"}
    if PERSONAL_API_KEY:
        headers["Authorization"] = f"Bearer {PERSONAL_API_KEY}"

    payload = {"query": user_text}
    try:
        resp = requests.post(PERSONAL_API_URL, headers=headers, json=payload, timeout=API_TIMEOUT)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError:
            return {"result_text": resp.text}
    except Exception as e:
        return {"error": str(e)}

def handle_note_intent(text: str) -> str:
    """Save a quick note to a timestamped file."""
    try:
        body = text.split(":", 1)[1].strip() if ":" in text else text
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"jarvis_note_{timestamp}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        return f"Saved note to {filename}."
    except Exception as e:
        return f"Failed to save note: {e}"

def process_text(user_text: str) -> str:
    """Decide what to do with recognized speech."""
    if not user_text:
        return "I didn't catch that. Please repeat."

    intent = extract_intent(user_text)
    print(f"[Intent detected] {intent}")

    if intent == "exit":
        return "exit_command"

    if intent == "note":
        return handle_note_intent(user_text)

    if intent == "call_api":
        print("Calling personal API...")
        api_result = call_personal_api(user_text)
        if isinstance(api_result, dict):
            if "error" in api_result:
                return f"API error: {api_result['error']}"
            if "result" in api_result:
                return f"API: {api_result['result']}"
            if "summary" in api_result:
                return f"API: {api_result['summary']}"
            try:
                short = json.dumps(api_result, ensure_ascii=False)
                if len(short) > 400:
                    short = short[:400] + "..."
                return f"API returned: {short}"
            except Exception:
                return f"API returned: {str(api_result)}"
        else:
            return f"API returned: {str(api_result)}"

    # default chat
    return llm_reply(user_text)

def recognize_speech_from_mic(timeout=None, phrase_time_limit=PHRASE_TIME_LIMIT):
    """Capture audio and return transcription."""
    response = {"success": True, "error": None, "transcription": None}
    try:
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=AMBIENT_ADJUST_SECONDS)
            print("Listening...")
            audio = recognizer.listen(source, phrase_time_limit=phrase_time_limit)
        try:
            transcription = recognizer.recognize_google(audio)
            response["transcription"] = transcription
        except sr.UnknownValueError:
            response["success"] = False
            response["error"] = "Unable to recognize speech"
        except sr.RequestError as e:
            response["success"] = False
            response["error"] = f"STT service error: {e}"
    except Exception as e:
        response["success"] = False
        response["error"] = f"Microphone error: {e}"
    return response

# ----------------- MAIN LOOP -----------------
def main_loop():
    speak("Hello Sir, Jarvis online. How can I assist?")
    try:
        while True:
            result = recognize_speech_from_mic()
            if not result["success"]:
                print("STT error:", result["error"])
                speak("I couldn't hear that. Please repeat.")
                continue

            text = result["transcription"]
            print("You said:", text)

            reply = process_text(text)
            if reply == "exit_command":
                speak("Goodbye! Shutting down.")
                print("Exiting Jarvis.")
                break

            print("Jarvis:", reply)
            speak(reply, block=True)

    except KeyboardInterrupt:
        print("User interrupted. Exiting.")
    except Exception:
        print("Unhandled exception in main loop:")
        traceback.print_exc()

if __name__ == "__main__":
    main_loop()
