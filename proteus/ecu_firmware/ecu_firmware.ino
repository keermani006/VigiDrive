#include <LiquidCrystal.h>

// --------------------------------------------------------------------------
// VigiDrive Automotive Safety ECU Firmware (ATmega328P / Arduino)
// --------------------------------------------------------------------------
// LCD pin assignment: RS=12 (PB4), E=11 (PB3), D4=5 (PD5), D5=4 (PD4), D6=3 (PD3), D7=2 (PD2)
LiquidCrystal lcd(12, 11, 5, 4, 3, 2);

// Output Actuator & Indicator Pins
const int PIN_GREEN  = 6;  // Pin 10 on ATmega328P (Safe State)
const int PIN_YELLOW = 7;  // Pin 11 on ATmega328P (Degraded State)
const int PIN_RED    = 8;  // Pin 12 on ATmega328P (Critical State)
const int PIN_BUZZER = 9;  // Pin 13 on ATmega328P (Acoustic Siren)
const int PIN_MOTOR  = 10; // Pin 14 on ATmega328P (Steering Wheel Haptic Motor)
const int PIN_RELAY  = 13; // Pin 17 on ATmega328P (Hazard Light Flasher Relay)

void setup() {
  // Start Hardware Serial @ 9600 baud (Pin 30 RX, Pin 31 TX)
  Serial.begin(9600);

  // Initialize 16x2 LCD
  lcd.begin(16, 2);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("VigiDrive ECU");
  lcd.setCursor(0, 1);
  lcd.print("STATUS: ONLINE");

  // Configure Actuator Outputs
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_MOTOR, OUTPUT);
  pinMode(PIN_RELAY, OUTPUT);

  // Initial State: Safe / Green LED
  digitalWrite(PIN_GREEN, HIGH);
  digitalWrite(PIN_YELLOW, LOW);
  digitalWrite(PIN_RED, LOW);
  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_MOTOR, LOW);
  digitalWrite(PIN_RELAY, LOW);
}

void loop() {
  if (Serial.available() > 0) {
    String state = Serial.readStringUntil('
');
    state.trim();

    if (state.length() == 0) return;

    // Update in-cabin HUD
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("DRIVER STATE:");
    lcd.setCursor(0, 1);
    lcd.print(state);

    if (state == "NORMAL") {
      digitalWrite(PIN_GREEN, HIGH);
      digitalWrite(PIN_YELLOW, LOW);
      digitalWrite(PIN_RED, LOW);
      digitalWrite(PIN_BUZZER, LOW);
      digitalWrite(PIN_MOTOR, LOW);
      digitalWrite(PIN_RELAY, LOW);
    }
    else if (state == "ATTENTION_DEGRADED") {
      digitalWrite(PIN_GREEN, LOW);
      digitalWrite(PIN_YELLOW, HIGH);
      digitalWrite(PIN_RED, LOW);
      digitalWrite(PIN_BUZZER, LOW);
      digitalWrite(PIN_MOTOR, LOW);
      digitalWrite(PIN_RELAY, LOW);
    }
    else if (state == "DROWSY" || state == "DISTRACTED") {
      digitalWrite(PIN_GREEN, LOW);
      digitalWrite(PIN_YELLOW, LOW);
      digitalWrite(PIN_RED, HIGH);
      digitalWrite(PIN_BUZZER, HIGH);
      digitalWrite(PIN_MOTOR, HIGH);   // Haptic steering vibrator ON
      digitalWrite(PIN_RELAY, LOW);
    }
    else if (state == "HIGH_RISK" || state == "ALERT") {
      digitalWrite(PIN_GREEN, LOW);
      digitalWrite(PIN_YELLOW, LOW);
      digitalWrite(PIN_RED, HIGH);
      digitalWrite(PIN_BUZZER, HIGH);
      digitalWrite(PIN_MOTOR, HIGH);   // Full steering vibration
      digitalWrite(PIN_RELAY, HIGH);  // Vehicle hazard lights ON
    }
  }
}
