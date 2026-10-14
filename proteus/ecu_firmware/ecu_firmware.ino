#include <LiquidCrystal.h>

// LCD pin assignment: RS=12, E=11, D4=5, D5=4, D6=3, D7=2
LiquidCrystal lcd(12, 11, 5, 4, 3, 2);

void setup() {
  lcd.begin(16, 2);
  
  // Set all candidate LED pins as outputs
  for (int p = 5; p <= 14; p++) {
    pinMode(p, OUTPUT);
    digitalWrite(p, LOW);
  }
}

void loop() {
  // -------------------------------------------------------------
  // STATE 1: NORMAL (Green LED ON) - 1.2s
  // -------------------------------------------------------------
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("DRIVER STATE:");
  lcd.setCursor(0, 1);
  lcd.print("NORMAL");

  // Green ON (Pin 6 & Pin 8)
  digitalWrite(6, HIGH); digitalWrite(8, HIGH);
  digitalWrite(7, LOW);  digitalWrite(9, LOW);
  digitalWrite(10, LOW); digitalWrite(12, LOW);
  delay(1200);

  // -------------------------------------------------------------
  // STATE 2: ATTENTION DEGRADED (Yellow LED ON) - 1.2s
  // -------------------------------------------------------------
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("DRIVER STATE:");
  lcd.setCursor(0, 1);
  lcd.print("DEGRADED");

  // Yellow ON (Pin 7 & Pin 9)
  digitalWrite(6, LOW);  digitalWrite(8, LOW);
  digitalWrite(7, HIGH); digitalWrite(9, HIGH);
  digitalWrite(10, LOW); digitalWrite(12, LOW);
  delay(1200);

  // -------------------------------------------------------------
  // STATE 3: DROWSY WARNING (Red LED ON) - 1.2s
  // -------------------------------------------------------------
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("DRIVER STATE:");
  lcd.setCursor(0, 1);
  lcd.print("DROWSY!");

  // Red ON (Pin 10 & Pin 12)
  digitalWrite(6, LOW);  digitalWrite(8, LOW);
  digitalWrite(7, LOW);  digitalWrite(9, LOW);
  digitalWrite(10, HIGH); digitalWrite(12, HIGH);
  delay(1200);

  // -------------------------------------------------------------
  // STATE 4: CRITICAL ALERT (Red LED ON) - 1.2s
  // -------------------------------------------------------------
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("DRIVER STATE:");
  lcd.setCursor(0, 1);
  lcd.print("CRITICAL ALERT!");

  digitalWrite(6, LOW);  digitalWrite(8, LOW);
  digitalWrite(7, LOW);  digitalWrite(9, LOW);
  digitalWrite(10, HIGH); digitalWrite(12, HIGH);
  delay(1200);
}
