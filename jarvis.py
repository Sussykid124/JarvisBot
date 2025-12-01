"""
Jarvis: Offline voice assistant using:
- Wake word + STT: Vosk
- LLM: Ollama (smollm:135m)
- TTS: espeak -> aplay (USB speaker, auto-detected)
- Arduino: motors + OLED face over serial

Stateless: no memory, each request is independent.
Python 3.11.x recommended.
"""

import json
import queue
import sys
import time
import threading
import subprocess
from typing import Optional, Tuple

import numpy as np
import requests
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# Try to import pyserial for Arduino; if missing, we just skip Arduino features
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

# ==========================
# CONFIGURATION
# ==========================

# Mic search – must appear somewhere in the mic's name
PREFERRED_INPUT_NAME_SUBSTRING = "Your mic name"

# Audio input defaults (will be adjusted at runtime)
SAMPLE_RATE = 16000
CHANNELS = 1

# Extra mic gain (software amplification)
MIC_GAIN = 2.0               # try 1.5–3.0; too high can clip

# Path to your Vosk model directory (download separately)
VOSK_MODEL_PATH = "models/vosk-model-small-en-us-0.15"  # <-- change if needed

# Wake words
WAKE_WORDS = ["jarvis", "hey jarvis"]

# STT behavior
MAX_UTTERANCE_SECONDS = 15          # allow a bit more time to speak
SILENCE_THRESHOLD = 0.004           # more sensitive to quiet speech
SILENCE_DURATION_END = 2.5          # seconds of silence before ending utterance

# LLM / Ollama
OLLAMA_URL = "http://localhost:11434/api/chat"
ACTIVE_MODEL = "smollm:135m"
LLM_TIMEOUT = 15                    # keep small for responsiveness

# TTS (espeak -> aplay on USB speaker)
TTS_RATE_WPM = 180                  # espeak speed
TTS_DEVICE = "default"              # will be updated at runtime
SPEAKER_NAME_SUBSTRING = "Your speaker name"  # must appear in `aplay -l` line

# Arduino / Serial
ARDUINO_PORT = None   # e.g. "/dev/ttyACM0"; if None we auto-detect
ARDUINO_BAUD = 9600

SYSTEM_PROMPT = (
    "You are Jarvis, a small offline voice assistant running on a low-power device. "
    "You must always be brief, concrete, and stay strictly on topic. "
    "Rules: "
    "1) Treat each user utterance independently; you do not have long-term memory. "
    "2) Respond with at most one or two short sentences. "
    "3) Do not ask the user questions unless they clearly asked you something first. "
    "4) Never introduce new topics, stories, philosophy, or questions the user did not mention. "
    "5) If the user just greets you (e.g. 'hi', 'hello'), reply with a simple greeting only. "
    "6) If you are unsure or lack information, say you are not sure instead of making things up."
)

# ==========================
# ARDUINO CONTROLLER
# ==========================

class ArduinoController:
    """
    Simple wrapper to send single-character commands to Arduino:
      Faces: 'O' = blink face, 'T' = thinking face
      Motors: 'F','B','L','R','S'
    """

    def __init__(self, port: Optional[str] = None, baudrate: int = ARDUINO_BAUD):
        self.ser: Optional["serial.Serial"] = None
        if serial is None:
            print("[ARDUINO] pyserial not installed; Arduino features disabled")
            return

        actual_port = port or self._auto_detect_port()
        if actual_port is None:
            print("[ARDUINO] No Arduino serial port found; Arduino features disabled")
            return

        try:
            self.ser = serial.Serial(actual_port, baudrate=baudrate, timeout=1)
            time.sleep(2.0)  # give Arduino time to reset
            print(f"[ARDUINO] Connected on {actual_port}")
        except Exception as e:
            print(f"[ARDUINO] Failed to open serial port {actual_port}: {e}")
            self.ser = None

    def _auto_detect_port(self) -> Optional[str]:
        """
        Try to find an Arduino-like device automatically.
        """
        try:
            ports = list(serial.tools.list_ports.comports())
        except Exception as e:
            print(f"[ARDUINO] Could not list serial ports: {e}")
            return None

        for p in ports:
            desc = (p.description or "").lower()
            if "arduino" in desc or "ch340" in desc or "usb serial" in desc:
                return p.device
        # fall back: if exactly one port, use it
        if len(ports) == 1:
            return ports[0].device
        return None

    def send(self, cmd: str) -> None:
        """
        Send a single-character command.
        """
        if not self.ser:
            return
        if not cmd:
            return
        try:
            self.ser.write(cmd[0].encode("ascii"))
        except Exception as e:
            print(f"[ARDUINO] Error sending '{cmd}': {e}")

    # Convenience helpers
    def face_blink(self) -> None:
        self.send("O")

    def face_think(self) -> None:
        self.send("T")

    def forward(self) -> None:
        self.send("F")

    def backward(self) -> None:
        self.send("B")

    def left(self) -> None:
        self.send("R")  # your Arduino: 'R' -> leftTurn()

    def right(self) -> None:
        self.send("L")  # your Arduino: 'L' -> rightTurn()

    def stop(self) -> None:
        self.send("S")


# ==========================
# TTS DEVICE DETECTION
# ==========================

def detect_tts_device() -> None:
    """
    Detect the USB speaker card from `aplay -l` by matching SPEAKER_NAME_SUBSTRING
    and set TTS_DEVICE to plughw:<card>,0. If not found, keep 'default'.
    """
    global TTS_DEVICE
    try:
        out = subprocess.check_output(["aplay", "-l"], text=True)
    except Exception as e:
        print(f"[TTS WARN] Could not run 'aplay -l': {e}, using default ALSA device")
        return

    card_num: Optional[int] = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("card ") and SPEAKER_NAME_SUBSTRING in line:
            parts = line.split()
            try:
                card_num = int(parts[1].rstrip(':'))
                break
            except ValueError:
                continue

    if card_num is None:
        print(f"[TTS WARN] USB speaker '{SPEAKER_NAME_SUBSTRING}' not found in 'aplay -l', using default ALSA device")
        return

    TTS_DEVICE = f"plughw:{card_num},0"
    print(f"[TTS] Using speaker device {TTS_DEVICE}")


detect_tts_device()

# ==========================
# TTS (espeak -> aplay)
# ==========================

def speak(text: str) -> None:
    """
    Use espeak to synthesize speech to stdout, then pipe it into
    aplay on the chosen speaker device. Also prints the text for debugging.
    """
    text = (text or "").strip()
    if not text:
        return

    print(f"[Jarvis speaking]: {text}")

    safe_text = text.replace('"', "'")

    cmd = (
        f'espeak -s {TTS_RATE_WPM} "{safe_text}" '
        f'--stdout | aplay -q -D {TTS_DEVICE}'
    )

    try:
        subprocess.run(cmd, shell=True, check=False)
    except Exception as e:
        print(f"[TTS ERROR] {e}", file=sys.stderr)


# ==========================
# LLM CLIENT (Ollama) - stateless
# ==========================

def ask_llm(user_text: str) -> Optional[str]:
    """
    Call Ollama's /api/chat with the chosen model, stateless,
    with conservative options to reduce hallucinations.
    """
    payload = {
        "model": ACTIVE_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "stream": False,
        "options": {
            "temperature": 0.35,
            "num_predict": 64,
        },
    }

    try:
        resp = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=LLM_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message") or {}
        content = msg.get("content", "").strip()
        return content or None
    except Exception as e:
        print(f"[ERROR] LLM failed: {e}", file=sys.stderr)
        return None


# ==========================
# INPUT DEVICE SELECTION
# ==========================

def find_input_device() -> Tuple[int, int]:
    """
    Find a suitable input device.
    1) Prefer one whose name contains PREFERRED_INPUT_NAME_SUBSTRING and max_input_channels >= 1
    2) Otherwise, use the first device with max_input_channels >= 1
    Returns (device_index, max_channels).
    """
    devices = sd.query_devices()
    print("[DEBUG] Available audio devices:")
    for idx, dev in enumerate(devices):
        print(f"  {idx}: {dev['name']} (in={dev['max_input_channels']}, out={dev['max_output_channels']})")

    preferred_idx: Optional[int] = None
    preferred_max_in = 0

    for idx, dev in enumerate(devices):
        if PREFERRED_INPUT_NAME_SUBSTRING in dev["name"] and dev["max_input_channels"] > 0:
            preferred_idx = idx
            preferred_max_in = dev["max_input_channels"]
            break

    if preferred_idx is not None:
        print(f"[DEBUG] Using preferred input device {preferred_idx}: "
              f"{devices[preferred_idx]['name']} (max_in={preferred_max_in})")
        return preferred_idx, preferred_max_in

    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            print(f"[DEBUG] Using fallback input device {idx}: "
                  f"{dev['name']} (max_in={dev['max_input_channels']})")
            return idx, dev["max_input_channels"]

    raise RuntimeError("No audio input device with input channels found.")


# ==========================
# AUDIO STREAM (minimal)
# ==========================

class AudioStream:
    """
    Simple mic input wrapper using sounddevice.
    """

    def __init__(self,
                 samplerate: int = SAMPLE_RATE,
                 channels: int = CHANNELS,
                 device: Optional[int] = None) -> None:
        if device is None:
            dev_index, max_in = find_input_device()
            channels = min(channels, max_in)
            if channels <= 0:
                raise RuntimeError(
                    f"Chosen input device {dev_index} has no input channels."
                )
            self.device = dev_index
            self.channels = channels
        else:
            self.device = device
            self.channels = channels

        self.samplerate = samplerate
        self.q: "queue.Queue[np.ndarray]" = queue.Queue()
        self.stream: Optional[sd.InputStream] = None
        self._stop = threading.Event()

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[AUDIO STATUS] {status}", file=sys.stderr)
        indata = indata * MIC_GAIN
        indata = np.clip(indata, -1.0, 1.0)
        if self.channels > 1:
            indata = indata.mean(axis=1, keepdims=True)
        self.q.put(indata.copy())

    def start(self) -> None:
        if self.stream is not None:
            return
        self._stop.clear()
        print(
            f"[DEBUG] Opening InputStream: samplerate={self.samplerate}, "
            f"channels={self.channels}, device={self.device}"
        )
        try:
            self.stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                callback=self._callback,
                device=self.device,
                blocksize=0,
            )
            self.stream.start()
        except Exception as e:
            print(f"[AUDIO ERROR] Failed to open input stream: {e}", file=sys.stderr)
            raise

    def stop(self) -> None:
        self._stop.set()
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                print(f"[AUDIO STOP ERROR]: {e}", file=sys.stderr)
            self.stream = None
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def read(self, timeout: Optional[float] = None) -> Optional[np.ndarray]:
        if self._stop.is_set():
            return None
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None


# ==========================
# VOSK SETUP
# ==========================

print("[INFO] Loading Vosk model...")
vosk_model = Model(VOSK_MODEL_PATH)
print("[INFO] Vosk model loaded.")

def create_wake_recognizer() -> KaldiRecognizer:
    grammar = json.dumps(WAKE_WORDS)
    return KaldiRecognizer(vosk_model, SAMPLE_RATE, grammar)

def create_full_recognizer() -> KaldiRecognizer:
    return KaldiRecognizer(vosk_model, SAMPLE_RATE)


# ==========================
# WAKE WORD
# ==========================

def contains_wake_word(text: str) -> bool:
    text = text.lower()
    for w in WAKE_WORDS:
        if w in text:
            return True
    return False

def wait_for_wake_word(audio_stream: AudioStream) -> None:
    recognizer = create_wake_recognizer()
    print("[INFO] Waiting for wake word...")

    while True:
        data = audio_stream.read(timeout=1.0)
        if data is None:
            continue

        pcm16 = (data * 32767).astype(np.int16).tobytes()

        if recognizer.AcceptWaveform(pcm16):
            try:
                j = json.loads(recognizer.Result())
                text = j.get("text", "")
            except json.JSONDecodeError:
                text = ""
            if text:
                print(f"[Wake STT]: {text}")
            if contains_wake_word(text):
                print("[INFO] Wake word detected!")
                return


# ==========================
# FULL UTTERANCE STT
# ==========================

def listen_for_utterance(audio_stream: AudioStream) -> Optional[str]:
    recognizer = create_full_recognizer()
    print("[INFO] Listening for utterance...")

    start_time = time.time()
    last_voice_time = start_time
    heard_any_voice = False
    transcript = ""

    while True:
        now = time.time()
        if now - start_time > MAX_UTTERANCE_SECONDS:
            print("[INFO] Max utterance duration reached.")
            break

        data = audio_stream.read(timeout=1.0)
        if data is None:
            continue

        rms = float(np.sqrt(np.mean(np.square(data))))
        is_voice = rms > SILENCE_THRESHOLD
        if is_voice:
            heard_any_voice = True
            last_voice_time = now

        pcm16 = (data * 32767).astype(np.int16).tobytes()

        if recognizer.AcceptWaveform(pcm16):
            try:
                j = json.loads(recognizer.Result())
                text = j.get("text", "")
            except json.JSONDecodeError:
                text = ""
            if text:
                if transcript:
                    transcript += " " + text
                else:
                    transcript = text

        if heard_any_voice and (now - last_voice_time) > SILENCE_DURATION_END:
            print("[INFO] Detected end of speech by silence.")
            break

    try:
        j = json.loads(recognizer.FinalResult())
        final_text = j.get("text", "")
    except json.JSONDecodeError:
        final_text = ""

    if final_text:
        if transcript:
            transcript += " " + final_text
        else:
            transcript = final_text

    transcript = transcript.strip()
    if transcript:
        print(f"[User]: {transcript}")
        return transcript
    else:
        print("[INFO] No speech recognized.")
        return None


# ==========================
# SIMPLE MOTOR COMMAND PARSER
# ==========================

def maybe_handle_motion_command(text: str, arduino: ArduinoController) -> bool:
    """
    Look for simple movement commands in the recognized text.
    Returns True if a motion command was handled.
    """
    if not arduino or not arduino.ser:
        return False

    t = text.lower()

    if "forward" in t or "ahead" in t:
        arduino.forward()
        speak("Moving forward.")
        return True
    if "back" in t or "reverse" in t:
        arduino.backward()
        speak("Moving backward.")
        return True
    if "left" in t:
        arduino.left()
        speak("Turning left.")
        return True
    if "right" in t:
        arduino.right()
        speak("Turning right.")
        return True
    if "stop" in t or "halt" in t:
        arduino.stop()
        speak("Stopping.")
        return True

    return False


# ==========================
# MAIN CONTROLLER
# ==========================

def main() -> None:
    arduino = ArduinoController(port=ARDUINO_PORT)

    audio_stream = AudioStream()
    audio_stream.start()

    if arduino and arduino.ser:
        arduino.face_blink()

    speak("Jarvis online. Say my name when you need me.")

    try:
        while True:
            wait_for_wake_word(audio_stream)

            speak("Yes?")

            user_text = listen_for_utterance(audio_stream)
            if not user_text:
                speak("I didn't catch that. Please try again.")
                continue

            # First, check if this is a motion command; if yes, skip LLM
            if maybe_handle_motion_command(user_text, arduino):
                if arduino and arduino.ser:
                    arduino.face_blink()
                continue

            # Show thinking face while LLM is working
            if arduino and arduino.ser:
                arduino.face_think()

            answer = ask_llm(user_text)

            if arduino and arduino.ser:
                arduino.face_blink()

            if not answer:
                speak("I'm having trouble thinking right now.")
                continue

            speak(answer)

    except KeyboardInterrupt:
        print("\n[INFO] Shutting down Jarvis.")
    finally:
        audio_stream.stop()
        if arduino and arduino.ser:
            try:
                arduino.stop()
                arduino.face_blink()
            except Exception:
                pass


if __name__ == "__main__":
    main()
