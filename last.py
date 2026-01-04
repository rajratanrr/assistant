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
from dataclasses import dataclass, asdict
from typing import Optional, Tuple, List
import requests
import speech_recognition as sr
import pyttsx3
import wikipedia
from openai import OpenAI

# CONFIG & CONSTANTS


STATE_PATH = os.path.expanduser("~/.jarvis_state.json")
REMINDERS_FILE_KEY = "reminders"
PREFS_KEY = "prefs"
APPS_KEY = "apps"
DEFAULT_CITY = "Delhi"

OPENAI_API_KEY = os.getenv("sk-...uLYA", "").strip()
OPENAI_MODEL = "gpt-4.1"  # keep as you had
OPENAI_TIMEOUT = 30  # seconds

# Open-Meteo endpoints
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# macOS Applications map (seed list; fuzzy match will help)
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

# GLOBALS


r = sr.Recognizer()
engine = pyttsx3.init()
client = None
last_spoken_text = ""  # for "repeat"
stop_speaking_flag = False  # for "stop" intent


# UTILS: STATE & SPEECH


def load_state():
    if not os.path.exists(STATE_PATH):
        return {PREFS_KEY: {"last_city": DEFAULT_CITY}, REMINDERS_FILE_KEY: [], APPS_KEY: {}}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {PREFS_KEY: {"last_city": DEFAULT_CITY}, REMINDERS_FILE_KEY: [], APPS_KEY: {}}

def save_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass  # tolerate write failures silently to not crash voice loop

def speak(msg: str):
    global last_spoken_text, stop_speaking_flag
    print("Jarvis:", msg)
    last_spoken_text = msg
    stop_speaking_flag = False

    # pyttsx3 is blocking; we allow an escape by checking stop flag between utterances
    engine.say(msg)
    try:
        engine.runAndWait()
    except RuntimeError:
        # rare engine race; reinit quietly
        try:
            engine.stop()
        except Exception:
            pass

def stop_speaking():
    global stop_speaking_flag
    stop_speaking_flag = True
    try:
        engine.stop()
    except Exception:
        pass

def repeat_last():
    if last_spoken_text:
        speak(last_spoken_text)
    else:
        speak("I haven't said anything to repeat yet.")

def help_message():
    speak(
        "You can say things like: what time is it, weather in Mumbai, "
        "open Chrome, search neural networks, YouTube lo-fi beats, "
        "remind me to drink water in 10 minutes, or calculate 20 percent of 250."
    )

# OPENAI CLIENT


def get_openai_client() -> Optional[OpenAI]:
    global client
    if client is not None:
        return client
    if not OPENAI_API_KEY:
        return None
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        return client
    except Exception as e:
        print("OpenAI init error:", e)
        return None

def call_ai(text: str) -> str:
    cli = get_openai_client()
    if not cli:
        return "AI service is not configured. Set the OPENAI_API_KEY environment variable."

    try:
        resp = cli.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are Jarvis, an AI voice assistant that gives clear, factual, and friendly answers."},
                {"role": "user", "content": text}
            ],
            timeout=OPENAI_TIMEOUT
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("AI Error:", e)
        return "I'm having trouble connecting to the AI service right now."

# TIME & WEATHER


def get_time() -> str:
    current = dt.datetime.now().strftime("%I:%M %p")
    return f"The time is {current}"

def geocode_city(city: str) -> Optional[Tuple[float, float, str, str]]:
    """Return (lat, lon, resolved_name, country_code) or None."""
    try:
        params = {"name": city, "count": 1}
        res = requests.get(GEOCODE_URL, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        if data.get("results"):
            first = data["results"][0]
            return (
                first["latitude"],
                first["longitude"],
                first.get("name", city),
                first.get("country_code", "")
            )
    except Exception as e:
        print("Geocode error:", e)
    return None

def parse_weather_query(text: str, state) -> Tuple[float, float, str]:
    """
    Return (lat, lon, label). Tries 'weather in <city>' else uses last_city.
    Falls back to Delhi if all fails.
    """
    m = re.search(r"\bweather\s+(in|at|for)\s+([a-zA-Z\s\-]+)$", text, re.IGNORECASE)
    city = None
    if m:
        city = m.group(2).strip()
    else:
        # Try bare city name like "what's mumbai weather"
        m2 = re.search(r"\b(in|at|for)\s+([a-zA-Z\s\-]+)\b.*weather\b", text, re.IGNORECASE)
        if m2:
            city = m2.group(2).strip()

    if city:
        geo = geocode_city(city)
        if geo:
            lat, lon, resolved, cc = geo
            state[PREFS_KEY]["last_city"] = resolved
            save_state(state)
            return lat, lon, resolved

    # No city found; use last city from state
    last_city = state.get(PREFS_KEY, {}).get("last_city", DEFAULT_CITY)
    geo = geocode_city(last_city)
    if geo:
        lat, lon, resolved, cc = geo
        return lat, lon, resolved

    # Hard fallback: Delhi coords
    return 28.6139, 77.2090, DEFAULT_CITY

def get_weather(text: str, state) -> str:
    lat, lon, label = parse_weather_query(text, state)
    try:
        params = {"latitude": lat, "longitude": lon, "current_weather": "true"}
        res = requests.get(WEATHER_URL, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        cw = data.get("current_weather", {})
        temp = cw.get("temperature")
        wind = cw.get("windspeed")
        if temp is not None and wind is not None:
            return f"Current weather in {label} is {temp}°C with wind {wind} km/h."
        return f"I couldn't parse the weather for {label} right now."
    except requests.RequestException:
        return "Network issue fetching weather. Please check your internet connection."
    except Exception:
        return "Unable to fetch weather right now."

# SYSTEM COMMANDS (macOS)


def open_app_on_mac(app_name: str, state):
    # Combine static APPS with learned user aliases
    user_apps = state.get(APPS_KEY, {})
    all_map = {**APPS, **user_apps}

    # Try exact and fuzzy matching
    keys = list(all_map.keys())
    best = difflib.get_close_matches(app_name.lower(), keys, n=1, cutoff=0.6)
    target_key = best[0] if best else None
    if not target_key:
        speak(f"I couldn't find an app similar to {app_name}.")
        return

    path = all_map[target_key]
    app_path_candidates = [
        f"/Applications/{path}",
        os.path.expanduser(f"~/Applications/{path}")
    ]
    for p in app_path_candidates:
        if os.path.exists(p):
            try:
                subprocess.Popen(f"open '{p}'", shell=True)
                speak(f"Opening {target_key}")
                return
            except Exception:
                speak(f"I found {target_key} but couldn't open it.")
                return

    speak(f"I found {target_key}, but the app isn't in Applications folders.")

def run_system_command(text: str, state):
    # Match "open <app>" at end or start
    m = re.search(r"\bopen\s+(?:the\s+)?(.+)$", text, re.IGNORECASE)
    if not m:
        speak("Say something like 'open Chrome' or 'open WhatsApp'.")
        return
    app = m.group(1).strip()
    # Avoid web mis-triggers like "open whatsapp web page"
    app = re.sub(r"\b(web|page|site)\b", "", app, flags=re.IGNORECASE).strip()
    if not app:
        speak("Tell me which app to open.")
        return
    open_app_on_mac(app, state)

# WEB COMMANDS


def run_web_command(text: str):
    t = text.lower()
    # Search
    m = re.search(r"\bsearch(?:\s+for)?\s+(.+)$", t)
    if m:
        query = m.group(1).strip()
        if query:
            webbrowser.open(f"https://www.google.com/search?q={requests.utils.quote(query)}")
            speak(f"Searching for {query}")
            return
        speak("What should I search for?")
        return

    # YouTube
    m2 = re.search(r"\byoutube(?:\s+(?:search|for))?\s+(.+)$", t)
    if m2:
        query = m2.group(1).strip()
        if query:
            webbrowser.open(f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}")
            speak(f"Opening YouTube results for {query}")
            return
        speak("What should I search on YouTube?")
        return

    speak("I couldn't understand your web request. Try 'search quantum computing'.")

# MATH (SAFE EVAL)


import ast
class SafeEval(ast.NodeVisitor):
    allowed_nodes = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Num, ast.Constant,
                     ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
                     ast.USub, ast.UAdd, ast.FloorDiv, ast.Load, ast.Call, ast.Name)
    allowed_funcs = {"sqrt": math.sqrt, "abs": abs, "round": round}
    allowed_names = {"pi": math.pi, "e": math.e}

    def visit(self, node):
        if not isinstance(node, self.allowed_nodes):
            raise ValueError("Disallowed expression.")
        return super().visit(node)

    def eval(self, node):
        if isinstance(node, ast.Expression):
            return self.eval(node.body)
        if isinstance(node, ast.Num):
            return node.n
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Only numbers are allowed.")
        if isinstance(node, ast.BinOp):
            l = self.eval(node.left)
            r = self.eval(node.right)
            if isinstance(node.op, ast.Add): return l + r
            if isinstance(node.op, ast.Sub): return l - r
            if isinstance(node.op, ast.Mult): return l * r
            if isinstance(node.op, ast.Div): return l / r
            if isinstance(node.op, ast.FloorDiv): return l // r
            if isinstance(node.op, ast.Mod): return l % r
            if isinstance(node.op, ast.Pow): return l ** r
            raise ValueError("Operator not allowed.")
        if isinstance(node, ast.UnaryOp):
            v = self.eval(node.operand)
            if isinstance(node.op, ast.UAdd): return +v
            if isinstance(node.op, ast.USub): return -v
            raise ValueError("Unary op not allowed.")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in self.allowed_funcs:
                args = [self.eval(a) for a in node.args]
                return self.allowed_funcs[node.func.id](*args)
            raise ValueError("Function not allowed.")
        if isinstance(node, ast.Name):
            if node.id in self.allowed_names:
                return self.allowed_names[node.id]
            raise ValueError("Name not allowed.")
        raise ValueError("Bad expression.")

def spoken_to_expr(text: str) -> str:
    t = text.lower()
    # Replace common verbal math phrases
    replacements = [
        (r"\bplus\b", "+"),
        (r"\bminus\b", "-"),
        (r"\b(divided by|over)\b", "/"),
        (r"\b(multiply|multiplied by|into|x)\b", "*"),
        (r"\bmod(?:ulo)?\b", "%"),
        (r"\bsquared\b", "**2"),
        (r"\bcubed\b", "**3"),
        (r"\bto the power of\b", "**"),
        (r"\bpercent of\b", "% of "),  # handle below
    ]
    for pat, repl in replacements:
        t = re.sub(pat, repl, t)

    # "A % of B" => (A/100)*B
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", t)
    if m:
        a, b = m.group(1), m.group(2)
        t = re.sub(re.escape(m.group(0)), f"({a}/100)*({b})", t, count=1)

    # Keep only safe tokens
    expr = re.sub(r"[^0-9+\-*/().% \^a-z]", "", t)
    expr = expr.replace("^", "**")
    return expr

def run_calculation(text: str):
    expr = spoken_to_expr(text)
    expr = expr.strip()
    if not expr or not re.search(r"[0-9()]", expr):
        speak("Please say a valid math expression.")
        return
    try:
        node = ast.parse(expr, mode="exec")
        # Convert 'exec' to 'Expression' if possible
        if len(node.body) == 1 and isinstance(node.body[0], ast.Expr):
            expr_node = ast.Expression(node.body[0].value)
        else:
            raise ValueError("Invalid expression.")
        val = SafeEval().eval(expr_node)
        speak(f"The result is {val}")
    except Exception:
        speak("I couldn't calculate that. Try a simpler expression like 12 into 5 or 20 percent of 250.")

# REMINDERS (PERSISTENT)

@dataclass
class Reminder:
    message: str
    due_at: str  # ISO timestamp

def parse_reminder(text: str) -> Optional[Reminder]:
    """
    Supports:
      - remind me to <task> in <N> minutes/hours
      - remind me in <N> minutes to <task>
      - remind me to <task> at HH:MM (24h or 12h with am/pm)
      - remind me to <task> tomorrow at HH:MM
    """
    t = text.strip()

    # in N minutes/hours
    m = re.search(r"remind me (?:to )?(.*)\b in (\d+)\s*(minute|minutes|min|hour|hours|hr|hrs)\b", t, re.IGNORECASE)
    if m:
        task = m.group(1).strip()
        n = int(m.group(2))
        unit = m.group(3).lower()
        delta = dt.timedelta(minutes=n) if unit.startswith("min") else dt.timedelta(hours=n)
        due = dt.datetime.now() + delta
        if not task:
            task = "do that thing"
        return Reminder(task, due.isoformat())

    # in N minutes to <task>
    m = re.search(r"remind me in (\d+)\s*(minute|minutes|min|hour|hours|hr|hrs)\b(?:\s+to\s+)(.+)$", t, re.IGNORECASE)
    if m:
        n = int(m.group(1)); unit = m.group(2).lower(); task = m.group(3).strip()
        delta = dt.timedelta(minutes=n) if unit.startswith("min") else dt.timedelta(hours=n)
        due = dt.datetime.now() + delta
        return Reminder(task or "do that thing", due.isoformat())

    # at HH:MM [am/pm]
    m = re.search(r"remind me (?:to )?(.+?)\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?\b", t, re.IGNORECASE)
    if m:
        task = m.group(1).strip()
        hour = int(m.group(2)); minute = int(m.group(3))
        ampm = m.group(4).lower() if m.group(4) else None
        now = dt.datetime.now()
        if ampm:
            if ampm == "pm" and hour != 12: hour += 12
            if ampm == "am" and hour == 12: hour = 0
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due <= now:
            # schedule for next day if time already passed
            due += dt.timedelta(days=1)
        return Reminder(task or "do that thing", due.isoformat())

    # tomorrow at HH:MM
    m = re.search(r"remind me (?:to )?(.+?)\s+tomorrow\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?\b", t, re.IGNORECASE)
    if m:
        task = m.group(1).strip()
        hour = int(m.group(2)); minute = int(m.group(3))
        ampm = m.group(4).lower() if m.group(4) else None
        if ampm:
            if ampm == "pm" and hour != 12: hour += 12
            if ampm == "am" and hour == 12: hour = 0
        due = dt.datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0) + dt.timedelta(days=1)
        return Reminder(task or "do that thing", due.isoformat())

    return None

def add_reminder(text: str, state):
    rem = parse_reminder(text)
    if not rem:
        speak("Try: remind me to stretch in 10 minutes, or remind me at 9:30 pm.")
        return
    reminders = state.get(REMINDERS_FILE_KEY, [])
    reminders.append(asdict(rem))
    state[REMINDERS_FILE_KEY] = reminders
    save_state(state)
    human_time = dt.datetime.fromisoformat(rem.due_at).strftime("%Y-%m-%d %I:%M %p")
    speak(f"Reminder noted for {human_time}: {rem.message}")

def check_due_reminders(state):
    now = dt.datetime.now()
    reminders = state.get(REMINDERS_FILE_KEY, [])
    keep: List[dict] = []
    for rdict in reminders:
        try:
            due = dt.datetime.fromisoformat(rdict["due_at"])
            if due <= now:
                speak(f"Reminder: {rdict['message']}")
            else:
                keep.append(rdict)
        except Exception:
            # skip malformed
            pass
    if len(keep) != len(reminders):
        state[REMINDERS_FILE_KEY] = keep
        save_state(state)

# WIKIPEDIA


def get_wikipedia_summary(query: str) -> str:
    try:
        cleaned = (query
                   .replace("who is", "")
                   .replace("what is", "")
                   .replace("tell me about", "")
                   .strip())
        summary = wikipedia.summary(cleaned, sentences=2, auto_suggest=False, redirect=True)
        try:
            page = wikipedia.page(cleaned, auto_suggest=False)
            url = page.url
            return f"{summary}\nSource: {url}"
        except Exception:
            return summary
    except wikipedia.exceptions.DisambiguationError as e:
        opts = ", ".join(e.options[:3])
        return f"That could refer to several topics. Do you mean {opts}?"
    except wikipedia.exceptions.PageError:
        return "I couldn't find information on that topic."
    except Exception:
        return "Error fetching information."

# INTENTS


def extract_intent(text: str) -> str:
    t = text.lower().strip()

    # Control intents
    if re.search(r"\b(stop|cancel)\b", t): return "stop"
    if re.search(r"\brepeat\b", t): return "repeat"
    if re.search(r"\bhelp\b", t): return "help"

    if "exit" in t or "bye" in t: return "exit"
    if "time" in t: return "time"
    if "weather" in t: return "weather"
    if re.search(r"\bopen\b", t): return "system"
    if re.search(r"\bsearch\b", t) or re.search(r"\byoutube\b", t): return "web"
    if re.search(r"[0-9]", t) or any(x in t for x in ["plus", "minus", "divided", "multiply", "into", "percent", "x"]):
        # heuristic for calc
        return "calc"
    if "remind me" in t or "reminder" in t or "note this" in t: return "reminder"
    if any(p in t for p in ["who is", "what is", "tell me about"]): return "wiki"
    return "chat"

# MAIN LOOP


def process_text(user_text: str, state):
    intent = extract_intent(user_text)
    print(f"[Intent Detected] {intent}")

    # periodic reminder check on each utterance
    check_due_reminders(state)

    if intent == "stop":
        stop_speaking()
        return
    if intent == "repeat":
        repeat_last()
        return
    if intent == "help":
        help_message()
        return

    if intent == "exit":
        speak("Goodbye! Have a great day.")
        return "exit_program"

    if intent == "time":
        speak(get_time())
        return

    if intent == "weather":
        speak(get_weather(user_text, state))
        return

    if intent == "system":
        run_system_command(user_text, state)
        return

    if intent == "web":
        run_web_command(user_text)
        return

    if intent == "calc":
        run_calculation(user_text)
        return

    if intent == "reminder":
        add_reminder(user_text, state)
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

def main():
    state = load_state()

    # init speaking rate/voice options (tweakable)
    try:
        rate = engine.getProperty('rate')
        engine.setProperty('rate', min(max(rate, 150), 190))
    except Exception:
        pass

    speak("Jarvis is online and ready.")
    while True:
        with sr.Microphone() as source:
            print("\nListening...")
            r.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = r.listen(source, timeout=8, phrase_time_limit=12)
            except Exception as e:
                print("Listen error:", e)
                continue

            try:
                text = r.recognize_google(audio)
                print("You said:", text)
                result = process_text(text, state)
                if result == "exit_program":
                    break
            except sr.UnknownValueError:
                print("Didn't catch that.")
            except sr.RequestError as e:
                print("Speech service error:", e)
            except Exception as e:
                print("Unexpected error:", e)

if __name__ == "__main__":
    main()
