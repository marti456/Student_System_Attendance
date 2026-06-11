/**
 * Attendance NFC Reader — ESP32-WROOM32 + PN532
 * ================================================
 * Наследник на стария код с ESP8266 + MFRC522 (RC522).
 *
 * ОСНОВНИ РАЗЛИКИ спрямо стария код:
 *
 * 1. МИКРОКОНТРОЛЕР: ESP8266 → ESP32
 *    - Различни WiFi библиотеки: ESP8266WiFi.h → WiFi.h
 *    - SPI пиновете вече се задават изрично в конструктора на Adafruit_PN532,
 *      защото ESP32 няма фиксирани SPI пинове като ESP8266.
 *
 * 2. NFC МОДУЛ: MFRC522 (RC522) → PN532
 *    - RC522 само ЧЕТЕ пасивни карти.
 *    - PN532 поддържа и APDU комуникация (ISO 7816-4),
 *      което е нужно за Android HCE (виртуална карта).
 *    - Различна библиотека: MFRC522.h → Adafruit_PN532.h
 *    - Различна инициализация: PCD_Init() → begin() + SAMConfig()
 *
 * 3. ИДЕНТИФИКАЦИЯ: RFID UID → HMAC payload
 *    - Стар код: чете физическия UID на картата (4 байта)
 *      и го праща директно към сървъра като "rfid_uid".
 *    - Нов код: изпраща SELECT AID APDU към телефона,
 *      телефонът отговаря с "ФН|ATC|HMAC" — криптографски
 *      подписан низ. ESP32 само го препраща към сървъра.
 *
 * 4. HTTP ФОРМАТ: form-urlencoded → JSON
 *    - Стар: "rfid_uid=AABBCCDD&room_number=305A"
 *    - Нов:  { "payload": "2301234|42|a3f9bc...", "room_number": "101" }
 *
 * 5. ISO-DEP активиране: readPassiveTargetID() → inListPassiveTarget()
 *    - readPassiveTargetID() спира на ISO 14443-3 ниво (само UID).
 *    - inListPassiveTarget() активира ISO-DEP (ISO 14443-4), което е
 *      задължително за APDU комуникация с Android HCE.
 *
 * 6. Payload парсване: търсене на нулев терминатор (0x00)
 *    - Android изпраща: ASCII_payload + 0x00 + SW(90 00)
 *    - Нулевият байт никога не може да е част от ASCII payload,
 *      затова е детерминистичен разделител.
 *    - Fallback: търсене на 90 00 навсякъде в response-а.
 *
 * 7. JSON БИБЛИОТЕКА: няма → ArduinoJson v7
 *    - JsonDocument вместо StaticJsonDocument (нов API в v7).
 *
 * Схема (само дясната страна на WROOM32 — 5V страна):
 *   3V3 → PN532 VCC  (задължително 3.3V!)
 *   GND → PN532 GND, катод на LED-овете (през 220Ω), GND на зумера
 *   14  → PN532 SCK
 *   13  → PN532 MOSI
 *   26  → PN532 MISO
 *   27  → PN532 SS / NSS
 *   25  → Зелен LED (+) — през 220Ω резистор
 *   32  → Червен LED (+) — през 220Ω резистор
 *   33  → Зумер (+)
 *
 * PN532 DIP превключватели → SPI режим:
 *   SEL0 = LOW (OFF), SEL1 = HIGH (ON)
 *
 * ЗАБЕЛЕЖКА за Android страната:
 *   NfcHceService.kt трябва да добавя 0x00 преди SW_OK:
 *     return payloadBytes + byteArrayOf(0x00) + SW_OK
 *   Това позволява надеждно разделяне на payload от статус думата.
 */

#include <Arduino.h>
#include <Adafruit_PN532.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"

#define PIN_PN532_SCK   14
#define PIN_PN532_MOSI  13
#define PIN_PN532_MISO  26
#define PIN_PN532_SS    27
#define PIN_LED_GREEN   25
#define PIN_LED_RED     32
#define PIN_BUZZER      33
#define BUZZER_CHANNEL  0

// Структура (ISO 7816-4):
//   CLA  INS  P1   P2   Lc   [AID - 7 байта]                    Le
//   0x00 0xA4 0x04 0x00 0x07 0xA0 0x00 0x00 0x02 0x47 0x10 0x01 0x00
static const uint8_t SELECT_AID_APDU[] = {
    0x00, 0xA4, 0x04, 0x00, 0x07,
    0xA0, 0x00, 0x00, 0x02, 0x47, 0x10, 0x01,
    0x00
};

// ── PN532 обект (Software SPI — всички пинове се подават на конструктора) ────
// ВАЖНО: Adafruit_PN532(ss) използва хардуерните дефолтни пинове на ESP32
//        (MISO=19, MOSI=23, SCK=18), а НЕ нашите custom пинове.
//        Затова подаваме всичките 4 пина → software SPI режим.
Adafruit_PN532 nfc(PIN_PN532_SCK, PIN_PN532_MISO, PIN_PN532_MOSI, PIN_PN532_SS);

// ── Визуална и звукова сигнализация ──────────────────────────────────────────
void signalSuccess() {
    digitalWrite(PIN_LED_GREEN, HIGH);
    ledcWriteTone(BUZZER_CHANNEL, 1000);
    delay(150);
    ledcWriteTone(BUZZER_CHANNEL, 1400);
    delay(200);
    ledcWriteTone(BUZZER_CHANNEL, 0);
    delay(1800);
    digitalWrite(PIN_LED_GREEN, LOW);
}

void signalError() {
    digitalWrite(PIN_LED_RED, HIGH);
    ledcWriteTone(BUZZER_CHANNEL, 300);
    delay(700);
    ledcWriteTone(BUZZER_CHANNEL, 0);
    delay(1300);
    digitalWrite(PIN_LED_RED, LOW);
}

// ── HTTP POST към FastAPI сървъра ─────────────────────────────────────────────
void sendToServer(const String& nfcPayload) {
    if (WiFi.status() != WL_CONNECTED) {
        WiFi.reconnect(); delay(3000);
        if (WiFi.status() != WL_CONNECTED) { signalError(); return; }
    }

    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(8000);

    JsonDocument doc;
    doc["payload"]     = nfcPayload;
    doc["room_number"] = ROOM_NUMBER;
    String body;
    serializeJson(doc, body);

    int code = http.POST(body);
    String resp = http.getString();
    http.end();

    Serial.printf("HTTP %d: %s\n", code, resp.c_str());
    if (code == 200) signalSuccess(); else signalError();
}

// ── Парсване на payload от response буфера ────────────────────────────────────
// Очакван формат от Android: ASCII_payload + 0x00 + 0x90 + 0x00
// Стратегия: Четем символи, докато не срещнем 0x00 (терминатор) или не свърши буферът.
String parsePayload(uint8_t* response, uint8_t responseLen) {
    if (responseLen < 38) { // Минимален възможен размер (1 + 1 за ФН + 4 + 32)
        Serial.println("Грешка: Пакетът е твърде къс.");
        return "";
    }

    // 1. Четем първия байт, за да разберем дължината на факултетния номер
    uint8_t fnLength = response[0];
    
    // Защитна проверка за препълване на буфера
    if (1 + fnLength + 4 + 32 > responseLen) {
        Serial.println("Грешка: Несъответствие в дължината на пакета.");
        return "";
    }

    // 2. Извличаме факултетния номер като текст (запазваме водещите нули!)
    String facultyNumber = "";
    for (int i = 0; i < fnLength; i++) {
        facultyNumber += (char)response[1 + i];
    }

    // 3. Намираме къде започва ATC (веднага след ФН)
    int atcOffset = 1 + fnLength;
    uint32_t atc = (response[atcOffset] << 24) | 
                   (response[atcOffset + 1] << 16) | 
                   (response[atcOffset + 2] << 8) | 
                   response[atcOffset + 3];

    // 4. Намираме къде започва HMAC (веднага след ATC)
    int hmacOffset = atcOffset + 4;
    String hmacHex = "";
    for (int i = 0; i < 32; i++) {
        char buf[3];
        sprintf(buf, "%02x", response[hmacOffset + i]);
        hmacHex += buf;
    }

    // 5. Сглобяваме финалния стринг за FastAPI
    String finalPayload = facultyNumber + "|" + String(atc) + "|" + hmacHex;
    
    Serial.println("Успешно декодиран динамичен пакет: " + finalPayload);
    return finalPayload;
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);

    pinMode(PIN_LED_GREEN, OUTPUT);
    pinMode(PIN_LED_RED,   OUTPUT);
    ledcSetup(BUZZER_CHANNEL, 1000, 8);
    ledcAttachPin(PIN_BUZZER, BUZZER_CHANNEL);
    digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_LED_RED,   LOW);

    // SPI.begin() НЕ се извиква — Adafruit_PN532 в software SPI режим
    // го инициализира сам чрез конструктора с 4 аргумента.

    nfc.begin();
    if (!nfc.getFirmwareVersion()) {
        Serial.println("PN532 не е намерен!");
        while (true) { digitalWrite(PIN_LED_RED, !digitalRead(PIN_LED_RED)); delay(300); }
    }
    nfc.SAMConfig();
    nfc.setPassiveActivationRetries(0xFF);
    Serial.println("PN532 OK");

    Serial.printf("Свързване с '%s'", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    for (int i = 0; i < 30 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500); Serial.print(".");
    }
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("\nWiFi грешка!");
        while (true) { digitalWrite(PIN_LED_RED, !digitalRead(PIN_LED_RED)); delay(100); }
    }
    Serial.printf("\nIP: %s\n", WiFi.localIP().toString().c_str());

    ledcWriteTone(BUZZER_CHANNEL, 880);
    delay(100);
    ledcWriteTone(BUZZER_CHANNEL, 0);
    Serial.println("Готов.");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
void loop() {
    //Serial.println("Waiting for phone...");

    // Активираме ISO-DEP (ISO 14443-4) протокола
    if (!nfc.inListPassiveTarget()) {
        delay(100); // Кратка пауза, за да не претоварваме процесора
        return;
    }

    Serial.println("Phone detected!");

    uint8_t response[64]; // Понеже пакетът е къс (~45 байта), 64 байта буфер ни е напълно достатъчен
    uint8_t responseLen = sizeof(response);

    // Правим САМО ЕДИН чист и директен опит за обмен на данни
    bool success = nfc.inDataExchange(
        (uint8_t*)SELECT_AID_APDU, sizeof(SELECT_AID_APDU),
        response, &responseLen
    );

    if (!success) {
        Serial.println("NFC Транзакцията се провали хардуерно.");
        signalError(); // Директна сигнализация за грешка
        delay(1000);   // Пауза, за да може студентът да си дръпне телефона
        return;
    }

    // Опит за парсване на прочетените данни
    String payload = parsePayload(response, responseLen);

    if (payload.length() > 0) {
        Serial.println("Успешно декодиран пакет: " + payload);
        Serial.println("Sending confirmation to phone...");
        uint8_t ackCommand[] = {0x00, 0x40, 0x00, 0x00}; 
        uint8_t ackResponse[16]; // по-голям буфер за всеки случай
        uint8_t ackResponseLen = sizeof(ackResponse);
        
        bool ackSuccess = nfc.inDataExchange(ackCommand, sizeof(ackCommand), ackResponse, &ackResponseLen);
        
        if (ackSuccess) {
            Serial.println("Phone acknowledged receipt!");
        } else {
            Serial.println("Failed to send confirmation to phone (but payload is captured).");
        }
        sendToServer(payload); 
        delay(3000); // Голяма пауза след успех
    } else {
        Serial.println("Грешка при парсване на данните (невалиден формат).");
        signalError(); //
        delay(1000);   //
    }
}