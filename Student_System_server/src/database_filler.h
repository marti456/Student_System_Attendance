#ifndef DATABASE_FILLER_H
#define DATABASE_FILLER_H

#include <Arduino.h>

// --- ПРИМЕРНИ ДАННИ ---
// ГРУПА 1: Студент 1 (Примерна карта: A1B2C3D4)
// ГРУПА 2: Студент 2 (Примерна карта: 5A6B7C8D)
// КУРС 1: Вградени Системи

const char* CREATE_TABLES = R"sql(
-- 1. Таблица Groups
CREATE TABLE IF NOT EXISTS Groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- 2. Таблица Courses (Дисциплини)
CREATE TABLE IF NOT EXISTS Courses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- 3. Таблица Students
CREATE TABLE IF NOT EXISTS Students (
    student_id INTEGER PRIMARY KEY,
    rfid_uid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    group_id INTEGER,
    FOREIGN KEY(group_id) REFERENCES Groups(id)
);

-- 4. Таблица Schedules (Графици)
CREATE TABLE IF NOT EXISTS Schedules (
    id INTEGER PRIMARY KEY,
    course_id INTEGER,
    room_number TEXT NOT NULL,
    group_id INTEGER,
    day_of_week INTEGER,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    FOREIGN KEY(course_id) REFERENCES Courses(id),
    FOREIGN KEY(group_id) REFERENCES Groups(id)
);

-- 5. Таблица Attendance
CREATE TABLE IF NOT EXISTS Attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    schedule_id INTEGER,
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY(student_id) REFERENCES Students(student_id),
    FOREIGN KEY(schedule_id) REFERENCES Schedules(id)
);
)sql";

#endif