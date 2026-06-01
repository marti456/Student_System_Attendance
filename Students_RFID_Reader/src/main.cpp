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

// ── Конфигурация ──────────────────────────────────────────────────────────────
static const char* WIFI_SSID   = "MERCUSYS_2C70";
static const char* WIFI_PASS   = "kolelo7141";
static const char* SERVER_URL  = "http://192.168.1.150:8000/checkin";
static const char* ROOM_NUMBER = "101";

// ── Пинове ───────────────────────────────────────────────────────────────────
#define PIN_PN532_SCK   14
#define PIN_PN532_MOSI  13
#define PIN_PN532_MISO  26
#define PIN_PN532_SS    27
#define PIN_LED_GREEN   25
#define PIN_LED_RED     32
#define PIN_BUZZER      33
#define BUZZER_CHANNEL  0

// ── SELECT AID APDU ──────────────────────────────────────────────────────────
// Казваме на телефона: "Искаме да говорим с нашето HCE приложение."
// AID-ът трябва да съвпада точно с apduservice.xml.
//
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
    String textHeader = "";
    int secondPipeIndex = -1;
    int pipeCount = 0;
    int hmacStartOffset = 0;

    // 1. Извличаме текстовата част до втория разделител '|'
    for (int i = 0; i < (int)responseLen; i++) {
        char c = (char)response[i];
        textHeader += c;
        if (c == '|') {
            pipeCount++;
            if (pipeCount == 2) {
                secondPipeIndex = i;
                hmacStartOffset = i + 1; // HMAC суровите байтове започват веднага след втория '|'
                break;
            }
        }
    }

    // Ако не сме намерили два пайпа, пакетът е невалиден
    if (secondPipeIndex == -1) {
        Serial.println("Грешка: Неуспешно откриване на текстовите разделители.");
        return "";
    }

    // 2. Четем следващите 32 байта (суровия HMAC-SHA256) и ги конвертираме в Hex текст
    String hmacHex = "";
    for (int i = 0; i < 32; i++) {
        int bytePos = hmacStartOffset + i;
        
        // Защита от излизане извън реално прочетения буфер
        if (bytePos >= responseLen) {
            Serial.println("Грешка: Буферът свърши преди да прочетем 32-та байта на HMAC.");
            return "";
        }
        
        char buf[3];
        sprintf(buf, "%02x", response[bytePos]); // В lowercase hex за FastAPI
        hmacHex += buf;
    }

    // 3. Сглобяваме финалния низ във формат "ФН|ATC|64_символа_HEX"
    String finalPayload = textHeader + hmacHex;
    
    Serial.println("Успешно декодиран цялостен payload: " + finalPayload);
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
    //Serial.println("Waiting...");

    // inListPassiveTarget() активира ISO-DEP (ISO 14443-4) протокола,
    // което е задължително за APDU комуникация с Android HCE.
    // readPassiveTargetID() спира само на ISO 14443-3 (UID четене) и
    // не може да изпраща APDU команди след това.
    if (!nfc.inListPassiveTarget()) return;

    Serial.println("Phone/card detected!");

    uint8_t response[255];
    uint8_t responseLen;
    bool ok = false;

    // Опитваме до 3 пъти — понякога Android HCE има кратко закъснение
    // при първото докосване (инициализация на услугата).
    for (int attempt = 1; attempt <= 3; attempt++) {
        responseLen = sizeof(response);
        ok = nfc.inDataExchange(
            (uint8_t*)SELECT_AID_APDU, sizeof(SELECT_AID_APDU),
            response, &responseLen
        );
        if (ok) {
            Serial.printf("OK на attempt %d\n", attempt);
            break;
        }
        Serial.printf("Attempt %d failed, retrying...\n", attempt);
        delay(80);
    }

    if (!ok) {
        // Дори при FAIL понякога има частичен отговор в буфера —
        // опитваме да парснем и него.
        Serial.println("inDataExchange failed — опитваме парсване на буфера...");
        // responseLen при FAIL е непроменен (255) — не го ползваме директно,
        // а търсим до първия валиден 0x00 или 90 00 в разумни граници (80 байта).
        uint8_t safeLen = 80;
        String payload = parsePayload(response, safeLen);
        if (payload.length() > 0) {
            Serial.println("Payload от partial response: " + payload);
            sendToServer(payload);
            delay(3000);
        } else {
            Serial.println("Парсването неуспешно. Raw (първи 80 байта):");
            for (int i = 0; i < safeLen; i++) Serial.printf("%02X ", response[i]);
            Serial.println();
            signalError();
            delay(1000);
        }
        return;
    }

    // Парсваме payload от успешния response
    String payload = parsePayload(response, responseLen);

    if (payload.length() > 0) {
        Serial.println("Success! Payload: " + payload);
        sendToServer(payload);
        delay(3000);
    } else {
        Serial.print("Парсването неуспешно. Raw response: ");
        for (int i = 0; i < responseLen; i++) Serial.printf("%02X ", response[i]);
        Serial.println();
        signalError();
        delay(1000);
    }
}