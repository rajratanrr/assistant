import speech_recognition as sr
import pyttsx3
import subprocess
import webbrowser
import datetime
import requests
import re
import json

from openai import OpenAI
client = OpenAI(api_key="sk-...QEoA")

WEATHER_URL = "https://api.open-meteo.com/v1/forecast?latitude=28.6139&longitude=77.2090&current_weather=true"

r = sr.Recognizer()
engine = pyttsx3.init()

APPS = {
    "chrome": "Google Chrome.app",
    "safari": "Safari.app",
    "whatsapp": "WhatsApp.app",
    "vscode": "Visual Studio Code.app",
    "terminal": "Terminal.app",
}

def speak(msg):
    print("Jarvis:", msg)
    engine.say(msg)
    engine.runAndWait()

def get_time():
    current = datetime.datetime.now().strftime("%I:%M %p")
    return f"The time is {current}"

def get_weather():
    try:
        res = requests.get(WEATHER_URL).json()
        temp = res["current_weather"]["temperature"]
        wind = res["current_weather"]["windspeed"]
        return f"The current weather is {temp}°C with wind speed {wind} km/h"
    except:
        return "Unable to fetch weather right now."

def run_system_command(text):
    text = text.lower()

    for name, path in APPS.items():
        if name in text:
            command = f"open '/Applications/{path}'"
            subprocess.Popen(command, shell=True)
            print(f"Opened {name}")
            return None

    return None

def run_web_command(text):
    if "search" in text:
        query = text.replace("search", "").strip()
        if query:
            webbrowser.open(f"https://www.google.com/search?q={query}")
            return None

    if "youtube" in text:
        query = text.replace("youtube", "").strip()
        webbrowser.open(f"https://www.youtube.com/results?search_query={query}")
        return None

    return None

def run_calculation(text):
    try:
        expression = re.sub(r"[^0-9+\-*/().]", "", text)
        if expression:
            result = eval(expression)
            print(f"Result: {result}")
        return None
    except:
        return None

def add_reminder(text):
    print("Reminder noted")
    return None

def call_ai(text):
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": text}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return "I'm having trouble connecting to GPT."

def extract_intent(text):
    text = text.lower()

    if "exit" in text or "bye" in text:
        return "exit"
    if "time" in text:
        return "time"
    if "weather" in text:
        return "weather"
    if "open" in text:
        return "system"
    if "search" in text or "youtube" in text:
        return "web"
    if any(x in text for x in ["+", "-", "into", "/", "x", "multiply"]):
        return "calc"
    if "remind" in text or "note" in text:
        return "reminder"

    return "chat"

def process_text(user_text):
    intent = extract_intent(user_text)
    print(f"[Intent] {intent}")

    if intent == "exit":
        speak("Goodbye!")
        return "exit_program"

    if intent == "time":
        speak(get_time())
        return None

    if intent == "weather":
        speak(get_weather())
        return None

    if intent == "system":
        run_system_command(user_text)
        return None

    if intent == "web":
        run_web_command(user_text)
        return None

    if intent == "calc":
        run_calculation(user_text)
        return None

    if intent == "reminder":
        add_reminder(user_text)
        return None

    # Chat: AI response
    reply = call_ai(user_text)
    speak(reply)
    return None

def main():
    speak("Jarvis ready and online.")

    while True:
        with sr.Microphone() as source:
            print("\nListening...")
            r.adjust_for_ambient_noise(source)
            audio = r.listen(source)

            try:
                text = r.recognize_google(audio)
                print("You said:", text)
                result = process_text(text)
                if result == "exit_program":
                    break

            except:
                print("Didn't catch that")


if __name__ == "__main__":
    main()
