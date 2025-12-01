# 🤖 JarvisBot

JarvisBot is a physical robot assistant built on top of **JarvisPipeline**.  
It adds motors, an OLED face, and USB serial communication so the robot can **move**, **express emotion**, and **respond intelligently**.

JarvisBot listens using JarvisPipeline, communicates with an Arduino-powered robot, and reacts both verbally and physically.

---

## ✨ Features

- **Animated OLED Face**
  - Blinking face (idle)
  - Thinking face (during LLM processing)

- **Motor Control**
  - Forward  
  - Backward  
  - Left / Right turns  
  - Full stop  

- **USB Serial Protocol**
  - Python sends single-character commands to Arduino
  - Arduino controls motors + display

- **Fully Offline**
  - All voice processing handled by JarvisPipeline (Vosk + Ollama + pyttsx3)

- **Works on Small Devices**
  - Orange Pi
  - Raspberry Pi
  - Linux/macOS/Binbows

---

## 🧠 How It Works

### 1. Voice Logic (JarvisPipeline)
JarvisPipeline handles:
- Wake word detection  
- Speech-to-text  
- Local LLM  
- Text-to-speech  

JarvisBot simply listens for certain keywords like:

- “move forward”
- “turn left”
- “stop”
- “show thinking face”

and translates them to robot commands.

---

### 2. Python → Arduino Serial Commands

Python sends **single-character commands**:

| Command | Action |
|--------|--------|
| `F`    | Forward |
| `B`    | Backward |
| `L`    | Turn left |
| `R`    | Turn right |
| `S`    | Stop motors |
| `O`    | Blinking face |
| `T`    | Thinking face |

Example in Python:

```python
arduino.write(b'F')   # move forward
arduino.write(b'T')   # switch to thinking face
```

---

### 3. Arduino Controls Motors + OLED

The Arduino sketch:
- drives motors using L298N
- draws faces on the SSD1306 OLED
- automatically blinks when idle
- switches to thinking face when instructed

---

## ⚙️ Requirements

### Hardware
- Arduino Uno/Nano/Mega
- L298N motor driver
- 2× DC motors
- SSD1306 OLED (128×64 I2C)
- USB cable for serial
- Separate battery for motors

### Software
- Python 3.11+
- JarvisPipeline installed
- Arduino IDE
- Python lib:

```bash
pip install pyserial
```

---

## ▶️ How to Run JarvisBot

### **1. Flash the Arduino**

Upload the provided `JarvisBot.ino` sketch to your Arduino.

### **2. Connect the Arduino**

Use USB (appears as `/dev/ttyUSB0` or COM ports on Binbows).

### **3. Start JarvisPipeline**

Runs the voice assistant:

```bash
python jarvis_pipeline.py
```

### **4. Run JarvisBot**

Controls motors & face:

```bash
python jarvisbot.py
```

### **5. Speak to the robot**

- “Hey Jarvis”
- “Move forward”
- “Turn left”
- “Stop”
- “Jarvis, think”
- “Jarvis, blink”

---

## 📁 Project Structure

Recommended GitHub layout:

```
JarvisBot/
│
├── arduino/
│   └── JarvisBot.ino        # The Arduino robot sketch
│
├── jarvisbot.py             # Python script controlling robot via serial
│
├── serial_commands.md       # Documentation for robot commands
│
├── README.md                # (this file)
│
└── LICENSE                  # Optional but recommended
```

### Optional folders:

```
examples/
  ├── test_motors.py
  └── test_face.py

assets/
  └── wiring-diagram.png
```

---

## 🌱 Future Improvements

- Add ultrasonic sensor for obstacle detection  
- Servo head movement  
- Wheel encoders  
- Emotional expressions  
- Sound effects  

---

## 📌 Notes

- JarvisBot requires **JarvisPipeline** running locally.
- Motors must NOT be powered from Arduino 5V.
- Protocol is simple and easily expandable.
