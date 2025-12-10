#include <Arduino.h>
#include <WiFi.h>
#include <SPI.h>
#include <SD.h>
#include <sqlite3.h>
#include <database_filler.h> // Включване на файла с SQL заявките
#include <ESPAsyncWebServer.h>
#include <ESPmDNS.h>
#include <time.h>

// --- КОНФИГУРАЦИЯ ---
const char* ssid = "DIR-657"; // "iPhone на Martin";
const char* password = "Bo035013";
IPAddress staticIP(192, 168, 0, 150);
IPAddress gateway(192, 168, 0, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress primaryDNS(192, 168, 0, 1);

const char* ntpServer = "time.google.com";

const long  gmtOffset_sec = 7200; 
const int   daylightOffset_sec = 3600;

#define DB_PATH "/sd/attendance.db"
#define SD_CS_PIN 27
const int HTTP_PORT = 80;

AsyncWebServer server(HTTP_PORT);

sqlite3 *db;


static int callback(void *data, int argc, char **argv, char **azColName) {
    return 0;
}

bool executeSQL(const char* sql) {
    char *errMsg = 0;
    int rc = sqlite3_exec(db, sql, callback, 0, &errMsg);
    if (rc != SQLITE_OK) {
        Serial.printf("SQL error: %s\n", errMsg);
        sqlite3_free(errMsg);
        return false;
    }
    return true;
}

void setupTime() {
  Serial.print("Синхронизиране на часа чрез NTP... ");
  configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);

  struct tm timeinfo;
  int retry = 0;
  while (!getLocalTime(&timeinfo) && retry < 10) {
    Serial.print(".");
    delay(500);
    retry++;
  }
  Serial.print(timeinfo.tm_hour);
  Serial.print(":");
  Serial.print(timeinfo.tm_min);
  Serial.print(":");
  Serial.println(timeinfo.tm_sec);
}

String getTimeNow(struct tm timeinfo) {
  char buf[20];
  strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &timeinfo);
  return String(buf);
}
bool setupDatabase() {
    Serial.println("Инициализация на SD карта...");
    if (!SD.begin(SD_CS_PIN)) {
        Serial.println("Грешка при инициализация на SD картата!");
        return false;
    }
    Serial.println("SD карта инициализирана успешно.");

    Serial.println("Отваряне на SQLite база данни...");
    int rc = sqlite3_open(DB_PATH, &db);
    if (rc) {
        Serial.printf("Не може да се отвори база данни: %s\n", sqlite3_errmsg(db));
        return false;
    }
    Serial.println("База данни отворена успешно.");

    if (!executeSQL(CREATE_TABLES)) {
        Serial.println("Грешка при създаване на таблици.");
        return false;
    }
    Serial.println("Таблици създадени/проверени успешно.");
    return true;
}


String processCheckIn(const String& uid, const String& room) {
    
    // 1. НАМИРАНЕ НА СТУДЕНТА И НЕГОВАТА ГРУПА
    String student_info;
    int student_id = 0;
    int student_group_id = 0;

    // Подготовка на SQL за SELECT
    char *sql_find_student = sqlite3_mprintf(
        "SELECT student_id, group_id, name FROM Students WHERE rfid_uid='%s';",
        uid.c_str()
    );
    Serial.printf("SQL Студент: %s\n", sql_find_student);
    sqlite3_stmt *stmt;
    if (sqlite3_prepare_v2(db, sql_find_student, -1, &stmt, 0) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            student_id = sqlite3_column_int(stmt, 0);
            student_group_id = sqlite3_column_int(stmt, 1);
            student_info = (const char*)sqlite3_column_text(stmt, 2);
        }
    }
    sqlite3_finalize(stmt);
    sqlite3_free(sql_find_student);

    if (student_id == 0) {
        return "ERROR: Невалидна RFID карта!";
    }
    
    // 2. НАМИРАНЕ НА Schedule в този кабинет

    String schedule_id_str = "";
    int current_schedule_id = 0;
    int slot_group_id = 0;
    int slot_course_id = 0;
    
    struct tm timeinfo;
    getLocalTime(&timeinfo);
    int day_of_week = timeinfo.tm_wday;
    if (day_of_week == 0){
      day_of_week = 7; 
    }
    String timestamp = getTimeNow(timeinfo);
    String current_time_str = timestamp.substring(11, 16);

    char *sql_find_slot = sqlite3_mprintf(
        "SELECT id, group_id, course_id FROM Schedules "
        "WHERE room_number = '%s' "
        "  AND day_of_week = %d "
        "  AND start_time <= '%s' "
        "  AND end_time   >= '%s';",
        room.c_str(), 
        day_of_week,
        current_time_str.c_str(), 
        current_time_str.c_str()
    );
    Serial.printf("SQL График: %s\n", sql_find_slot);
    if (sqlite3_prepare_v2(db, sql_find_slot, -1, &stmt, 0) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            current_schedule_id = sqlite3_column_int(stmt, 0);
            slot_group_id = sqlite3_column_int(stmt, 1);
            slot_course_id = sqlite3_column_int(stmt, 2);
        }
    }
    sqlite3_finalize(stmt);
    sqlite3_free(sql_find_slot);
    
    if (current_schedule_id == 0) {
        return "ERROR: В момента няма насрочен час в този кабинет.";
    }

    int existing_attendance = 0;
    
    char *sql_check_duplicate = sqlite3_mprintf(
        "SELECT COUNT(*) FROM Attendance WHERE student_id = %d AND schedule_id = %d;",
        student_id, current_schedule_id
    );

    sqlite3_stmt *stmt_check;
    if (sqlite3_prepare_v2(db, sql_check_duplicate, -1, &stmt_check, 0) == SQLITE_OK) {
        if (sqlite3_step(stmt_check) == SQLITE_ROW) {
            existing_attendance = sqlite3_column_int(stmt_check, 0);
        }
    }
    sqlite3_finalize(stmt_check);
    sqlite3_free(sql_check_duplicate);

    if (existing_attendance > 0) {
        return "SUCCESS: Присъствието на " + student_info + " вече е записано за този час.";
    }

    // 3. ОПРЕДЕЛЯНЕ НА СТАТУСА
    String status = "";
    String log_message = "";

    // Редовно присъствие
    if (student_group_id == slot_group_id) {
        status = "Присъствие";
        log_message = "Успешно присъствие на редовен час.";
    } 
    // Отработване или Грешка
    else {
        int group_has_course = 0;
        char *sql_group_check = sqlite3_mprintf(
            "SELECT COUNT(*) FROM Schedules WHERE group_id = %d AND course_id = %d;",
            student_group_id, slot_course_id
        );

        sqlite3_stmt *stmt_group_check;
        if (sqlite3_prepare_v2(db, sql_group_check, -1, &stmt_group_check, 0) == SQLITE_OK) {
            if (sqlite3_step(stmt_group_check) == SQLITE_ROW) {
                group_has_course = sqlite3_column_int(stmt_group_check, 0);
            }
        }
        sqlite3_finalize(stmt_group_check);
        sqlite3_free(sql_group_check);
        
        if (group_has_course > 0) {
            status = "Отработване";
            log_message = "Успешно отработване с друга група.";
        } else {
            // Студентът е объркал курса/кабинета.
            return "ERROR: Студентът не изучава курса, който се провежда в момента. (Объркан кабинет)";
        }
    }

    // 4. ЗАПИС В ТАБЛИЦА ATTENDANCE
    char *sql_insert_attendance = sqlite3_mprintf(
        "INSERT INTO Attendance (student_id, schedule_id, timestamp, status) VALUES (%d, %d, '%s', '%s');",
        student_id, current_schedule_id, timestamp.c_str(), status.c_str()
    );

    if (!executeSQL(sql_insert_attendance)) {
        sqlite3_free(sql_insert_attendance);
        return "ERROR: Грешка при запис в база данни!";
    }
    sqlite3_free(sql_insert_attendance);

    return "SUCCESS: " + log_message + " (" + student_info + ", " + status + ")";
}


void handleCheckin(AsyncWebServerRequest *request) {
    if (request->method() == HTTP_POST) {
        String uid = "";
        String room = "";
        
        int params = request->args();
        for (int i = 0; i < params; i++) {
            if (request->argName(i) == "rfid_uid") {
                uid = request->arg(i);
            }
            if (request->argName(i) == "room_number") {
                room = request->arg(i);
            }
        }
        
        if (uid.length() == 0 || room.length() == 0) {
            request->send(400, "text/plain", "ERROR: Липсва rfid_uid или room_number.");
            return;
        }

        Serial.printf("\nСвободна памет преди SQL: %d bytes ---\n", ESP.getFreeHeap());
        String result = processCheckIn(uid, room);
        Serial.println("-> Резултат: " + result);

        if (result.startsWith("SUCCESS")) {
            request->send(200, "text/plain", result);
        } else {
            request->send(403, "text/plain", result);
        }

    } else {
        request->send(405, "text/plain", "Method not allowed. Use POST.");
    }
}

void setup_wifi() {
    if (!WiFi.config(staticIP, gateway, subnet, primaryDNS)) {
        Serial.println("Неуспешна конфигурация на статичен IP!");
    }
    Serial.print("Свързване към WiFi...");
    WiFi.begin(ssid, password);
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi Свързан!");
        Serial.print("IP Адрес: ");
        Serial.println(WiFi.localIP());
    } else {
        Serial.println("\nНеуспешно свързване с WiFi!");
    } 
}

void setup() {
    Serial.begin(115200);
    SPI.begin(14, 12, 13, SD_CS_PIN);
    setup_wifi();
    setupTime();
    if (!setupDatabase()) {
        Serial.println("Критична грешка: Не може да се инициализира базата данни.");
        return; 
    }

    server.on("/checkin", HTTP_POST, handleCheckin);
    
    server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
        request->send(200, "text/plain", "Attendance Server OK. Ready to receive checkin POSTs.");
    });
    
    server.begin();
    Serial.println("HTTP Асинхронен сървър стартиран.");
}

void loop() {
    // pass
}