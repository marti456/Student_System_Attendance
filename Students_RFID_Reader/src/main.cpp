#include <SPI.h>
#include <MFRC522.h>
#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>

const char* ssid = "DIR-657";
const char* password = "Bo035013";

const String serverIP = "192.168.0.150";
const int serverPort = 80;
const String endpoint = "/checkin";
String serverPath = "http://" + serverIP +":"+ serverPort + endpoint;
// RFID RC522
#define RST_PIN D3  // GPIO0
#define SS_PIN D8   // GPIO15
#define BUZZER_PIN D0  // GPIO16
#define RED_LED_PIN D1  // GPIO5
#define GREEN_LED_PIN D2  // GPIO4

MFRC522 mfrc522(SS_PIN, RST_PIN);

unsigned long previousMillis = 0;
const long interval = 2000;
String roomNumber = "305A";


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

void sendDataToServer(String uid) {
  if (WiFi.status() == WL_CONNECTED) {
    
    WiFiClient client;
    HTTPClient http;
    
    Serial.print("[HTTP] Сървър: ");
    Serial.println(serverPath);

    http.begin(client, serverPath);
    
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");

    String httpRequestData = "rfid_uid=" + uid + "&room_number=" + roomNumber;
    Serial.print("Изпращане на данни: ");
    Serial.println(httpRequestData);

    int httpResponseCode = http.POST(httpRequestData);
    
    if (httpResponseCode > 0) {
      Serial.printf("[HTTP] Отговор Код: %d\n", httpResponseCode);
      String response = http.getString();
      Serial.println(response);
      
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
    client.flush();
    client.stop();
    Serial.print("Free heap after request: ");
    Serial.println(ESP.getFreeHeap());
    Serial.println("Очаква се RFID карта...");
  } else {
    Serial.println("WiFi връзката е прекъсната.");
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println();
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
    
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);
  noTone(BUZZER_PIN);
  setup_wifi();

  SPI.begin();
  mfrc522.PCD_Init();
  Serial.println("Очаква се RFID карта...");
}

void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    if ( ! mfrc522.PICC_IsNewCardPresent()) {
      return;
    }

    if ( ! mfrc522.PICC_ReadCardSerial()) {
      return;
    }
    
    String rfid_uid = uidToString(mfrc522.uid.uidByte, mfrc522.uid.size);
    Serial.print("Прочетено UID: ");
    Serial.println(rfid_uid);

    sendDataToServer(rfid_uid);

    mfrc522.PICC_HaltA();
    
    mfrc522.PCD_StopCrypto1();
  }
}