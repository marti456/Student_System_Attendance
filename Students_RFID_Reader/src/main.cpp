#include <SPI.h>
#include <Adafruit_PN532.h>
#include <WiFi.h>
#include <HTTPClient.h>

// Wi-Fi настройки
const char* ssid = "DIR-657";
const char* password = "Bo035013";

// Сървър настройки
const String serverIP = "192.168.0.150";
const int serverPort = 80;
const String endpoint = "/checkin";
String serverPath = "http://" + serverIP + ":" + String(serverPort) + endpoint;
String roomNumber = "305A";

// Дефиниране на пинове от едната страна на ESP32 за SPI
#define SCK_PIN  14
#define MOSI_PIN 13
#define MISO_PIN 26
#define SS_PIN   27

// Дефиниране на пинове за индикация
#define GREEN_LED_PIN 25
#define RED_LED_PIN   32
#define BUZZER_PIN    33

// Инициализация на PN532 чрез Software SPI
Adafruit_PN532 nfc(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);

unsigned long previousMillis = 0;
const long interval = 2000;

// APDU команда за селектиране на Android приложението (AID: F0 01 02 03 04 05 06)
uint8_t selectApdu[] = {
  0x00, /* CLA */
  0xA4, /* INS - Select */
  0x04, /* P1  - By Name */
  0x00, /* P2  - First/only occurrence */
  0x07, /* Lc  - Length of AID (7 bytes) */
  0xF0, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, /* AID */
  0x00  /* Le  */
};

void setup_wifi() {
  Serial.print("Свързване към ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);
  
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Свързан!");
  Serial.print("IP Адрес: ");
  Serial.println(WiFi.localIP());
}

void sendDataToServer(String studentUid) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    
    Serial.print("[HTTP] Сървър: ");
    Serial.println(serverPath);

    http.begin(serverPath);
    // FastAPI очаква JSON
    http.addHeader("Content-Type", "application/json");

    // Формиране на JSON payload
    String jsonPayload = "{\"rfid_uid\":\"" + studentUid + "\",\"room_number\":\"" + roomNumber + "\"}";
    Serial.print("Изпращане на данни: ");
    Serial.println(jsonPayload);

    int httpResponseCode = http.POST(jsonPayload);
    
    if (httpResponseCode > 0) {
      Serial.printf("[HTTP] Отговор Код: %d\n", httpResponseCode);
      String response = http.getString();
      Serial.println(response);
      
      // Успешно чекиране
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
    http.end();
  } else {
    Serial.println("WiFi връзката е прекъсната.");
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
    
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);
  
  setup_wifi();

  nfc.begin();

  uint32_t versiondata = nfc.getFirmwareVersion();
  if (!versiondata) {
    Serial.print("PN532 не е открит през SPI! Провери окабеляването и ключетата на модула.");
    while (1); // Спира изпълнението
  }
  
  // Конфигуриране на PN532
  nfc.SAMConfig();
  nfc.setPassiveActivationRetries(0x11);
  Serial.println("Очаква се Android устройство (NFC HCE)...");
}

void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    boolean success;
    uint8_t response[32];
    uint8_t responseLength = 32;

    // Опит за изпращане на APDU командата към телефона
    success = nfc.inDataExchange(selectApdu, sizeof(selectApdu), response, &responseLength);

    if (success) {
      Serial.println("Успешна комуникация с Android приложението!");
      
      // Преобразуване на получения отговор в String
      String studentUid = "";
      for (uint8_t i = 0; i < responseLength; i++) {
        studentUid += (char)response[i];
      }
      
      Serial.print("Прочетен идентификатор: ");
      Serial.println(studentUid);

      sendDataToServer(studentUid);
    }
  }
}