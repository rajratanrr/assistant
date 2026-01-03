import speech_recognition as sr
import pyttsx3
import subprocess
import webbrowser
import datetime
import requests
import re
import wikipedia
from openai import OpenAI

# Initialize OpenAI
client = OpenAI(api_key="sk-...")  # <-- Replace with your actual key

# Weather API (Delhi default)
WEATHER_URL = "https://api.open-meteo.com/v1/forecast?latitude=28.6139&longitude=77.2090&current_weather=true"

# Initialize recognizer and voice engine
r = sr.Recognizer()
engine = pyttsx3.init()

# Installed applications mapping
APPS = {
    "chrome": "Google Chrome.app",
    "safari": "Safari.app",
    "whatsapp": "WhatsApp.app",
    "vscode": "Visual Studio Code.app",
    "terminal": "Terminal.app",
}

# ---------- Core Functions ----------

def speak(msg):
    """Speak and print output"""
    print("Jarvis:", msg)
    engine.say(msg)
    engine.runAndWait()

def get_time():
    current = datetime.datetime.now().strftime("%I:%M %p")
    return f"The time is {current}"

def get_weather():
    """Fetch live weather"""
    try:
        res = requests.get(WEATHER_URL).json()
        temp = res["current_weather"]["temperature"]
        wind = res["current_weather"]["windspeed"]
        return f"The current weather is {temp}°C with wind speed {wind} km/h"
    except:
        return "Unable to fetch weather right now."

def run_system_command(text):
    """Open apps on Mac"""
    text = text.lower()
    for name, path in APPS.items():
        if name in text:
            command = f"open '/Applications/{path}'"
            subprocess.Popen(command, shell=True)
            speak(f"Opening {name}")
            return
    speak("I couldn't find that app.")

def run_web_command(text):
    """Handle web search or YouTube"""
    text = text.lower()
    if "search" in text:
        query = text.replace("search", "").strip()
        if query:
            webbrowser.open(f"https://www.google.com/search?q={query}")
            speak(f"Searching for {query}")
            return
    if "youtube" in text:
        query = text.replace("youtube", "").strip()
        webbrowser.open(f"https://www.youtube.com/results?search_query={query}")
        speak(f"Opening YouTube results for {query}")
        return
    speak("I couldn't understand your web request.")

def run_calculation(text):
    """Simple math operations"""
    try:
        expression = re.sub(r"[^0-9+\-*/().]", "", text)
        if expression:
            result = eval(expression)
            speak(f"The result is {result}")
            return
    except:
        speak("I couldn't calculate that.")

def add_reminder(text):
    """Simple reminder system"""
    speak("Reminder noted.")

# ---------- AI & Wikipedia ----------

def get_wikipedia_summary(query):
    """Fetch 2-line summary from Wikipedia"""
    try:
        query = query.replace("who is", "").replace("what is", "").replace("tell me about", "").strip()
        summary = wikipedia.summary(query, sentences=2)
        return summary
    except wikipedia.exceptions.DisambiguationError as e:
        return f"Can you be more specific? {', '.join(e.options[:3])}"
    except wikipedia.exceptions.PageError:
        return "I couldn't find information on that topic."
    except Exception:
        return "Error fetching information."

def call_ai(text):
    """Ask GPT for a smart answer"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "You are Jarvis, an AI voice assistant that gives clear, factual, and friendly answers."},
                {"role": "user", "content": text}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("AI Error:", e)
        return "I'm having trouble connecting to the AI service."

# ---------- Intent & Processing ----------

def extract_intent(text):
    """Recognize user command category"""
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
    if "who is" in text or "what is" in text or "tell me about" in text:
        return "wiki"
    return "chat"

def process_text(user_text):
    """Decide what to do with input"""
    intent = extract_intent(user_text)
    print(f"[Intent Detected] {intent}")

    if intent == "exit":
        speak("Goodbye! Have a great day.")
        return "exit_program"

    if intent == "time":
        speak(get_time())
        return

    if intent == "weather":
        speak(get_weather())
        return

    if intent == "system":
        run_system_command(user_text)
        return

    if intent == "web":
        run_web_command(user_text)
        return

    if intent == "calc":
        run_calculation(user_text)
        return

    if intent == "reminder":
        add_reminder(user_text)
        return

    if intent == "wiki":
        summary = get_wikipedia_summary(user_text)
        if "I couldn't find" in summary or "Error" in summary:
            summary = call_ai(user_text)
        speak(summary)
        return

    # Default: Chat with AI
    reply = call_ai(user_text)
    speak(reply)

# ---------- Main Loop ----------

def main():
    speak("Jarvis is online and ready.")
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
            except Exception as e:
                print("Didn't catch that:", e)

if __name__ == "__main__":
    main()
