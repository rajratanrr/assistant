import os
import json
import re
import time
import math
import datetime as dt
import subprocess
import webbrowser
import difflib
import threading
import socket
from dataclasses import dataclass, asdict
from typing import Optional, Tuple, List

# Online dependencies
import requests
import speech_recognition as sr
import pyttsx3
import wikipedia
from openai import OpenAI

# Offline dependencies
import numpy as np
import sounddevice as sd
import whisper


# =====================================================
# AUTO ONLINE/OFFLINE SWITCH
# =====================================================

def is_internet_available():
    """Check internet connectivity."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except:
        return False


# =====================================================
# LOAD OFFLINE WHISPER MODEL
# =====================================================

print("Loading Whisper BASE model (offline STT)...")
whisper_model = whisper.load_model("base")
print("Whisper is ready.")


# =====================================================
# GLOBALS
# =====================================================

r = sr.Recognizer()
engine = pyttsx3.init()
client = None
last_spoken_text = ""
stop_speaking_flag = False

STATE_PATH = os.path.expanduser("~/.jarvis_state.json")
REMINDERS_FILE_KEY = "reminders"
PREFS_KEY = "prefs"
APPS_KEY = "apps"
DEFAULT_CITY = "Delhi"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = "gpt-4.1"
OPENAI_TIMEOUT = 30

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

APPS = {
    "chrome": "Google Chrome.app",
    "google chrome": "Google Chrome.app",
    "safari": "Safari.app",
    "whatsapp": "WhatsApp.app",
    "vscode": "Visual Studio Code.app",
    "visual studio code": "Visual Studio Code.app",
    "terminal": "Terminal.app",
    "notes": "Notes.app",
    "calendar": "Calendar.app",
    "music": "Music.app",
}


# =====================================================
# BASIC UTILITIES
# =====================================================

def speak(msg: str):
    global last_spoken_text, stop_speaking_flag
    print("Jarvis:", msg)
    last_spoken_text = msg
    stop_speaking_flag = False
    engine.say(msg)
    try:
        engine.runAndWait()
    except:
        pass


def stop_speaking():
    global stop_speaking_flag
    stop_speaking_flag = True
    try:
        engine.stop()
    except:
        pass


def repeat_last():
    if last_spoken_text:
        speak(last_spoken_text)
    else:
        speak("I haven't said anything yet.")


def load_state():
    if not os.path.exists(STATE_PATH):
        return {PREFS_KEY: {"last_city": DEFAULT_CITY}, REMINDERS_FILE_KEY: [], APPS_KEY: {}}
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except:
        return {PREFS_KEY: {"last_city": DEFAULT_CITY}, REMINDERS_FILE_KEY: [], APPS_KEY: {}}


def save_state(state):
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except:
        pass


# =====================================================
# ONLINE AI CLIENT
# =====================================================

def get_openai_client():
    global client
    if client is not None:
        return client
    if not OPENAI_API_KEY:
        return None
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        return client
    except:
        return None


def call_ai(text):
    cli = get_openai_client()
    if not cli:
        return "AI offline mode active."

    try:
        resp = cli.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are Jarvis, a helpful assistant."},
                {"role": "user", "content": text}
            ],
            timeout=OPENAI_TIMEOUT
        )
        return resp.choices[0].message.content.strip()
    except:
        return "AI offline fallback active."


# =====================================================
# ONLINE FUNCTIONS (Weather, Wiki, Search)
# =====================================================

def get_time():
    return dt.datetime.now().strftime("It is %I:%M %p")


def geocode_city(city):
    try:
        res = requests.get(GEOCODE_URL, params={"name": city, "count": 1}, timeout=5)
        data = res.json()
        if data.get("results"):
            c = data["results"][0]
            return c["latitude"], c["longitude"], c["name"]
    except:
        return None


def get_weather(text, state):
    if not is_internet_available():
        return "Weather is unavailable in offline mode."

    m = re.search(r"weather in ([a-zA-Z\s]+)", text.lower())
    city = m.group(1).strip() if m else state[PREFS_KEY].get("last_city", DEFAULT_CITY)

    geo = geocode_city(city)
    if not geo:
        return "Unable to find that city."

    lat, lon, name = geo
    try:
        res = requests.get(WEATHER_URL, params={"latitude": lat, "longitude": lon, "current_weather": "true"}, timeout=5)
        cw = res.json().get("current_weather", {})
        return f"Weather in {name}: {cw.get('temperature')}°C, wind {cw.get('windspeed')} km/h."
    except:
        return "Failed to fetch weather."


def get_wikipedia_summary(query):
    if not is_internet_available():
        return "Wikipedia is unavailable offline."

    try:
        cleaned = query.replace("who is", "").replace("what is", "").replace("tell me about", "").strip()
        return wikipedia.summary(cleaned, sentences=2)
    except:
        return "Couldn't find information."


# =====================================================
# OFFLINE SPEECH-TO-TEXT (WHISPER)
# =====================================================

def record_audio(duration=4, fs=16000):
    speak("Listening offline...")
    audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype="float32")
    sd.wait()
    return np.squeeze(audio)


def whisper_transcribe(audio):
    audio = whisper.pad_or_trim(audio)
    mel = whisper.log_mel_spectrogram(audio).to(whisper_model.device)
    result = whisper_model.decode(mel)
    return result.text.strip()


# =====================================================
# SYSTEM COMMANDS (macOS)
# =====================================================

def run_system_command(text, state):
    m = re.search(r"open (.+)", text.lower())
    if not m:
        speak("Say 'open Chrome' or 'open Terminal'.")
        return

    app = m.group(1).strip()
    app = re.sub(r"(web|page|site)", "", app)

    all_map = {**APPS, **state.get(APPS_KEY, {})}
    best = difflib.get_close_matches(app, all_map.keys(), n=1, cutoff=0.6)

    if not best:
        speak("App not found.")
        return

    path = f"/Applications/{all_map[best[0]]}"
    if os.path.exists(path):
        subprocess.Popen(f"open '{path}'", shell=True)
        speak(f"Opening {best[0]}")
    else:
        speak("App is not installed.")


# =====================================================
# MATH (OFFLINE SAFE)
# =====================================================

def run_calculation(text):
    text = text.replace("into", "*").replace("x", "*").replace("plus", "+").replace("minus", "-")
    expr = re.sub(r"[^0-9+\-*/().]", "", text)
    try:
        speak(f"The result is {eval(expr)}")
    except:
        speak("Invalid calculation.")


# =====================================================
# OFFLINE CHAT FALLBACK
# =====================================================

def offline_chat(text):
    replies = {
        "hello": "Hello! I am offline now.",
        "hi": "Hi there!",
        "who are you": "I am Jarvis in offline mode.",
        "how are you": "I am fully operational offline."
    }
    for k in replies:
        if k in text.lower():
            speak(replies[k])
            return
    speak("I'm offline and cannot answer that fully.")


# =====================================================
# INTENT RECOGNITION (Works in both modes)
# =====================================================

def extract_intent(text):
    t = text.lower()
    if "time" in t: return "time"
    if "open" in t: return "system"
    if "weather" in t: return "weather"
    if "who is" in t or "what is" in t or "tell me about" in t: return "wiki"
    if any(x in t for x in ["+", "minus", "into", "multiply"]): return "calc"
    if "bye" in t or "exit" in t: return "exit"
    return "chat"


# =====================================================
# MASTER PROCESSOR
# =====================================================

def process_text(text, state):
    intent = extract_intent(text)
    online = is_internet_available()

    if intent == "time":
        speak(get_time())
    elif intent == "system":
        run_system_command(text, state)
    elif intent == "weather":
        speak(get_weather(text, state))
    elif intent == "wiki":
        speak(get_wikipedia_summary(text) if online else "Offline mode: cannot access Wikipedia.")
    elif intent == "calc":
        run_calculation(text)
    elif intent == "chat":
        speak(call_ai(text) if online else offline_chat(text))
    elif intent == "exit":
        speak("Goodbye!")
        return "exit"


# =====================================================
# MAIN LOOP
# =====================================================

def main():
    state = load_state()
    speak("Hybrid Jarvis Activated.")

    while True:
        online = is_internet_available()

        try:
            if online:
                # ONLINE SPEECH-TO-TEXT
                with sr.Microphone() as source:
                    print("\n[ONLINE] Listening...")
                    r.adjust_for_ambient_noise(source)
                    audio = r.listen(source)
                text = r.recognize_google(audio)
                print("You said:", text)

            else:
                # OFFLINE STT (WHISPER)
                print("\n[OFFLINE] Listening...")
                audio = record_audio()
                text = whisper_transcribe(audio)
                print("You said:", text)

            result = process_text(text, state)
            if result == "exit":
                break

        except Exception as e:
            print("Error:", e)
            speak("I didn't catch that.")


if __name__ == "__main__":
    main()
