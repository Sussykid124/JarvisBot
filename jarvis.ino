// ==== L298N Motor Driver Pins ====
const int ENA = 5;   // Left motor speed (PWM)
const int IN1 = 7;
const int IN2 = 8;

const int ENB = 6;   // Right motor speed (PWM)
const int IN3 = 9;
const int IN4 = 10;

// ==== OLED Includes ====
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

// ==== Face Modes ====
enum FaceMode {
  FACE_BLINK,
  FACE_THINK
};

FaceMode currentFace = FACE_BLINK;

// ==== Blinking State ====
bool blinkOpen = true;
unsigned long lastBlinkChange = 0;

const unsigned long BLINK_OPEN_DURATION   = 3000;
const unsigned long BLINK_CLOSED_DURATION = 200;

// ==== Forward Declarations ====
void forward();
void backward();
void leftTurn();
void rightTurn();
void stopMotors();
void drawFace(FaceMode mode);
void drawBlinkFace(bool open);

void setup() {
  Serial.begin(9600);

  // Motor pins
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);

  pinMode(ENB, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);

  stopMotors();

  // OLED init
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("SSD1306 failed 😵");
    for (;;);
  }
  display.clearDisplay();

  currentFace = FACE_BLINK;
  blinkOpen = true;
  lastBlinkChange = millis();
  drawFace(currentFace);

  Serial.println("🤖 READY!");
  Serial.println("Motor controls: F B L R S");
  Serial.println("Face controls: O (blink), T (think)");
}

void loop() {
  // Handle Serial commands
  if (Serial.available()) {
    char cmd = Serial.read();

    switch (cmd) {

      // ==== Motor commands ====
      case 'B':
        forward();
        break;

      case 'F':
        backward();
        break;

      case 'R':
        leftTurn();
        break;

      case 'L':
        rightTurn();
        break;

      case 'S':
        stopMotors();
        break;

      // ==== Face commands ====
      case 'O':
        currentFace = FACE_BLINK;
        blinkOpen = true;
        lastBlinkChange = millis();
        drawFace(currentFace);
        Serial.println("Face → Blinking 👀✨");
        break;

      case 'T':
        currentFace = FACE_THINK;
        drawFace(currentFace);
        Serial.println("Face → Thinking 🤔");
        break;

      default:
        Serial.println("Unknown command 😅 (F B L R S | O T)");
        break;
    }
  }

  // ==== Blinking logic ====
  if (currentFace == FACE_BLINK) {
    unsigned long now = millis();
    unsigned long interval = blinkOpen ? BLINK_OPEN_DURATION : BLINK_CLOSED_DURATION;

    if (now - lastBlinkChange >= interval) {
      blinkOpen = !blinkOpen;
      lastBlinkChange = now;
      drawBlinkFace(blinkOpen);
    }
  }
}

// ============================================================
//                     MOTOR FUNCTIONS
// ============================================================

void forward() {
  Serial.println("Forward ➡️");

  analogWrite(ENA, 200);
  analogWrite(ENB, 200);

  // Correct motor directions
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);

  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
}

void backward() {
  Serial.println("Backward ⬅️");

  analogWrite(ENA, 200);
  analogWrite(ENB, 200);

  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);

  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
}

void leftTurn() {
  Serial.println("Left ↪️");

  analogWrite(ENA, 180);
  analogWrite(ENB, 180);

  // Left wheel backward
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);

  // Right wheel forward
  digitalWrite(IN3, HIGH);
  digitalWrite(IN4, LOW);
}

void rightTurn() {
  Serial.println("Right ↩️");

  analogWrite(ENA, 180);
  analogWrite(ENB, 180);

  // Left wheel forward
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);

  // Right wheel backward
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, HIGH);
}

void stopMotors() {
  Serial.println("Stop 🛑");

  analogWrite(ENA, 0);
  analogWrite(ENB, 0);

  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);

  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
}

// ============================================================
//                     FACE FUNCTIONS
// ============================================================

void drawFace(FaceMode mode) {
  display.clearDisplay();

  if (mode == FACE_BLINK) {
    drawBlinkFace(blinkOpen);
  }

  else if (mode == FACE_THINK) {
    // Eyes
    display.fillRect(30, 22, 16, 16, SSD1306_WHITE);
    display.fillRect(82, 22, 16, 16, SSD1306_WHITE);

    // Dots (...)
    int dotY = 50;
    int dotSize = 4;
    display.fillCircle(48, dotY, dotSize, SSD1306_WHITE);
    display.fillCircle(64, dotY, dotSize, SSD1306_WHITE);
    display.fillCircle(80, dotY, dotSize, SSD1306_WHITE);
    display.display();
  }
}

void drawBlinkFace(bool open) {
  display.clearDisplay();

  if (open) {
    // Open eyes
    display.fillRect(30, 20, 20, 20, SSD1306_WHITE);
    display.fillRect(80, 20, 20, 20, SSD1306_WHITE);
  } else {
    // Closed eyes
    display.fillRect(30, 27, 20, 6, SSD1306_WHITE);
    display.fillRect(80, 27, 20, 6, SSD1306_WHITE);
  }

  display.display();
}
