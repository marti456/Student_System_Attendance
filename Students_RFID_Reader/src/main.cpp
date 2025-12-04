#include <SPI.h>
#include <MFRC522.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>

// --- КОНФИГУРАЦИЯ НА МРЕЖАТА ---
const char* ssid = "MERCUSYS_2C70";     // Сменете с името на Вашата Wi-Fi мрежа
const char* password = "kolelo7141"; // Сменете с паролата на Вашата Wi-Fi мрежа

// --- КОНФИГУРАЦИЯ НА СЪРВЪРА (ESP32) ---
// Трябва да използвате IP адреса, който ESP32-сървърът ще получи в мрежата.
const String serverIP = "192.168.1.100";
const int serverPort = 80;
const String endpoint = "/checkin";

// --- КОНФИГУРАЦИЯ НА RFID ЧЕТЕЦА (RC522) ---
#define RST_PIN D3  // GPIO0
#define SS_PIN D8   // GPIO15
#define BUZZER_PIN D0  // GPIO14
#define RED_LED_PIN D1  // GPIO15
#define GREEN_LED_PIN D2  // GPIO16

MFRC522 mfrc522(SS_PIN, RST_PIN);  // Създаване на инстанция

// --- ГЛОБАЛНИ ПРОМЕНЛИВИ ---
unsigned long previousMillis = 0;
const long interval = 2000; // Интервал за следващо сканиране (2 секунди)
String roomNumber = "305A";

// =======================================================
// ФУНКЦИИ
// =======================================================

// Функция за свързване към Wi-Fi
void setup_wifi() {
  Serial.print("Свързване към ");
  Serial.println(ssid);

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("");
  Serial.println("WiFi Свързан!");
  Serial.print("IP Адрес: ");
  Serial.println(WiFi.localIP());
}

// Функция за конвертиране на UID в низ (String)
String uidToString(byte *buffer, byte bufferSize) {
  String uid = "";
  for (byte i = 0; i < bufferSize; i++) {
    if (buffer[i] < 0x10) {
      uid += "0";
    }
    uid += String(buffer[i], HEX);
  }
  return uid;
}

// Функция за изпращане на POST заявка към ESP32 сървъра
void sendDataToServer(String uid) {
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClient client;
    HTTPClient http;

    String serverPath = "http://" + serverIP + endpoint;
    Serial.print("[HTTP] Сървър: ");
    Serial.println(serverPath);

    // Начало на HTTP сесията
    http.begin(client, serverPath);
    
    // Задаване на Content-Type
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");

    // Създаване на тялото на POST заявката
    String httpRequestData = "rfid_uid=" + uid + "&room_number=" + roomNumber;
    Serial.print("Изпращане на данни: ");
    Serial.println(httpRequestData);

    // Изпращане на заявката
    int httpResponseCode = http.POST(httpRequestData);
    
    // Проверка за отговор
    if (httpResponseCode > 0) {
      Serial.printf("[HTTP] Отговор Код: %d\n", httpResponseCode);
      String response = http.getString();
      Serial.println(response);
      
      // Добавете тук логика за светване на зелен/червен LED в зависимост от отговора
      // напр. ако отговорът съдържа "Успешно" -> зелен LED
      if (httpResponseCode == 200) {
        digitalWrite(GREEN_LED_PIN, HIGH);
        tone(BUZZER_PIN, 1000, 150);
      } else {
        digitalWrite(RED_LED_PIN, HIGH);
        tone(BUZZER_PIN, 300, 400);
      }
      
    } else {
      Serial.printf("[HTTP] Грешка, Код: %d\n", httpResponseCode);
      digitalWrite(RED_LED_PIN, HIGH);
      tone(BUZZER_PIN, 300, 400);
    }
    delay(500); 
    noTone(BUZZER_PIN);
    
    delay(1500); 
    
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(RED_LED_PIN, LOW);
    // Приключване на HTTP сесията
    http.end();
    Serial.println("Очаква се RFID карта...");
  } else {
    Serial.println("WiFi връзката е прекъсната.");
  }
}

// =======================================================
// ОСНОВНИ ФУНКЦИИ
// =======================================================

void setup() {
  Serial.begin(115200);
  Serial.println();
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
    
    // Първоначално изключваме всички индикатори
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);
  noTone(BUZZER_PIN);
  setup_wifi();

  SPI.begin();       // Инициализиране на SPI
  mfrc522.PCD_Init();  // Инициализиране на RC522
  Serial.println("Очаква се RFID карта...");
}

void loop() {
  unsigned long currentMillis = millis();

  // Проверка дали е минал интервалът за сканиране
  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    // Търсене на нова карта
    if ( ! mfrc522.PICC_IsNewCardPresent()) {
      return;
    }

    // Избор на карта
    if ( ! mfrc522.PICC_ReadCardSerial()) {
      return;
    }
    
    // Извличане на UID и конвертиране в String
    String rfid_uid = uidToString(mfrc522.uid.uidByte, mfrc522.uid.size);
    Serial.print("Прочетено UID: ");
    Serial.println(rfid_uid);

    // Изпращане на данните към сървъра
    sendDataToServer(rfid_uid);

    // Стопиране на четенето на картата, докато не бъде премахната
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
  }
}