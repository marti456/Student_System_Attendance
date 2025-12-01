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

const char* INSERT_DATA = R"sql(
-- Попълване на Groups
INSERT OR IGNORE INTO Groups (id, name) VALUES (1, '37A');
INSERT OR IGNORE INTO Groups (id, name) VALUES (2, '37B');

-- Попълване на Courses
INSERT OR IGNORE INTO Courses (id, name) VALUES (101, 'Вградени Системи - Упр.');

-- Попълване на Students
-- Група 37A (ID 1)
INSERT OR IGNORE INTO Students (student_id, rfid_uid, name, group_id) VALUES (1001, 'a1b2c3d4', 'Иван Петров', 1); 
-- Група 37B (ID 2)
INSERT OR IGNORE INTO Students (student_id, rfid_uid, name, group_id) VALUES (1002, '5a6b7c8d', 'Мария Георгиева', 2); 

-- Попълване на Schedules (Курс 101: Вградени системи)
-- Слот 1: Основен час за Група 37А (ID 1) - Кабинет 305A
INSERT OR IGNORE INTO Schedules (id, course_id, room_number, group_id, day_of_week, start_time, end_time) 
VALUES (1, 101, '305A', 1, 6, '11:00', '13:00'); 

-- Слот 2: Отработващ час за Група 37В (ID 2) - Кабинет 305B
INSERT OR IGNORE INTO Schedules (id, course_id, room_number, group_id, day_of_week, start_time, end_time) 
VALUES (2, 101, '305B', 2, 6, '14:00', '16:00'); 
)sql";

#endif