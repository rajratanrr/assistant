import os
import json
import time
import threading
import subprocess
import traceback
import webbrowser
import requests
import speech_recognition as sr
import pyttsx3
from openai import OpenAI
import re
from datetime import datetime, timedelta


OPENAI_API_KEY = "sk-...QEoA"
PERSONAL_API_KEY = ""  # Optional
PERSONAL_API_URL = ""  # Optional, like "https://your-api-url.com"

client = OpenAI(api_key=OPENAI_API_KEY)

TTS_RATE = 170
PHRASE_TIME_LIMIT = 12
AMBIENT_ADJUST_SECONDS = 1.5
API_TIMEOUT = 8
REMINDERS = []

recognizer = sr.Recognizer()
microphone = sr.Microphone()

tts_engine = pyttsx3.init()
tts_engine.setProperty("rate", TTS_RATE)

def speak(text, block=True):
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
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": user_text}]
        )
        return response.choices[0].message["content"]
    except Exception as e:
        return f"GPT error: {e}"

def extract_intent(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in ("exit", "quit", "stop", "bye", "goodbye")):
        return "exit"
    if any(k in t for k in ("note:", "take note", "remember")):
        return "note"
    if any(k in t for k in ("get info", "status", "fetch", "call api", "my api")):
        return "call_api"
    if any(k in t for k in ("open ", "launch ", "run ", "start ", "close ")):
        return "system_command"
    if any(k in t for k in ("search ", "google ", "wiki ", "wikipedia ")):
        return "web_command"
    if "remind me" in t or "set reminder" in t:
        return "reminder"
    if any(k in t for k in ("calculate ", "what is ", "convert ")):
        return "calculation"
    return "chat"

def call_personal_api(user_text: str) -> dict:
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
    try:
        body = text.split(":", 1)[1].strip() if ":" in text else text
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"jarvis_note_{timestamp}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        return f"Saved note to {filename}."
    except Exception as e:
        return f"Failed to save note: {e}"

def run_system_command(command: str) -> str:
    try:
        cmd = command.lower()
        if "open" in cmd or "launch" in cmd or "start" in cmd:
            app = cmd.replace("open", "").replace("launch", "").replace("start", "").strip()
            speak(f"Opening {app}")
            if os.name == "posix":
                subprocess.run(["open", "-a", app])
            elif os.name == "nt":
                subprocess.run(["start", "", app], shell=True)
            return f"Opened {app}"
        if "close" in cmd or "quit" in cmd:
            app = cmd.replace("close", "").replace("quit", "").strip()
            speak(f"Closing {app}")
            if os.name == "posix":
                subprocess.run(["pkill", "-x", app])
            elif os.name == "nt":
                subprocess.run(["taskkill", "/IM", f"{app}.exe", "/F"], shell=True)
            return f"Closed {app}"
        return "Command not recognized."
    except Exception as e:
        return f"System command error: {e}"

def run_web_command(command: str) -> str:
    try:
        cmd = command.lower()
        if "google" in cmd or "search" in cmd:
            query = cmd.replace("google", "").replace("search", "").strip()
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(url)
            return f"Searching Google for '{query}'"
        if "wiki" in cmd or "wikipedia" in cmd:
            query = cmd.replace("wiki", "").replace("wikipedia", "").strip()
            url = f"https://en.wikipedia.org/wiki/{query.replace(' ', '_')}"
            webbrowser.open(url)
            return f"Searching Wikipedia for '{query}'"
        return "Web command not recognized."
    except Exception as e:
        return f"Web command error: {e}"

def parse_reminder(text: str):
    try:
        t = text.lower()
        message = t.split("remind me", 1)[1].strip()
        match = re.search(r"in (\d+) (second|seconds|minute|minutes)", message)
        if match:
            value = int(match.group(1))
            unit = match.group(2)
            seconds = value * 60 if "minute" in unit else value
            return time.time() + seconds, message
        match = re.search(r"at (\d{1,2}):(\d{2})", message)
        if match:
            now = datetime.now()
            h, m = int(match.group(1)), int(match.group(2))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target.timestamp() < time.time():
                target += timedelta(days=1)
            return target.timestamp(), message
        return time.time() + 5, message
    except:
        return time.time() + 5, text

def add_reminder(text: str) -> str:
    ts, msg = parse_reminder(text)
    REMINDERS.append({"time": ts, "text": msg})
    return f"Reminder set: {msg}"

def check_reminders():
    while True:
        now = time.time()
        for r in REMINDERS[:]:
            if now >= r["time"]:
                speak(f"Reminder: {r['text']}")
                REMINDERS.remove(r)
        time.sleep(1)

def run_calculation(command: str) -> str:
    try:
        expr = command.replace("calculate","").replace("what is","").replace("convert","").strip()
        result = eval(expr)
        return f"The result is {result}"
    except Exception as e:
        return f"Calculation error: {e}"

def process_text(user_text: str) -> str:
    if not user_text:
        return "I didn't catch that. Please repeat."
    intent = extract_intent(user_text)
    print(f"[Intent detected] {intent}")
    if intent == "exit":
        return "exit_command"
    if intent == "note":
        return handle_note_intent(user_text)
    if intent == "call_api":
        return json.dumps(call_personal_api(user_text))
    if intent == "system_command":
        return run_system_command(user_text)
    if intent == "web_command":
        return run_web_command(user_text)
    if intent == "reminder":
        return add_reminder(user_text)
    if intent == "calculation":
        return run_calculation(user_text)
    return llm_reply(user_text)

def recognize_speech_from_mic(timeout=None, phrase_time_limit=PHRASE_TIME_LIMIT):
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

def main_loop():
    speak("Hello Sir, Jarvis online. How can I assist?")
    threading.Thread(target=check_reminders, daemon=True).start()
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