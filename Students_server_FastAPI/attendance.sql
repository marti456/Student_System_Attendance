BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS "Attendance" (
	"id"	INTEGER NOT NULL,
	"student_id"	INTEGER,
	"schedule_id"	INTEGER,
	"timestamp"	DATETIME,
	"status"	VARCHAR NOT NULL,
	PRIMARY KEY("id"),
	CONSTRAINT "uq_student_schedule" UNIQUE("student_id","schedule_id"),
	FOREIGN KEY("schedule_id") REFERENCES "Schedules"("id"),
	FOREIGN KEY("student_id") REFERENCES "Students"("student_id")
);
CREATE TABLE IF NOT EXISTS "Courses" (
	"id"	INTEGER NOT NULL,
	"name"	VARCHAR NOT NULL,
	PRIMARY KEY("id"),
	UNIQUE("name")
);
CREATE TABLE IF NOT EXISTS "Groups" (
	"id"	INTEGER NOT NULL,
	"name"	VARCHAR NOT NULL,
	"year"	INTEGER NOT NULL,
	"major"	VARCHAR NOT NULL,
	PRIMARY KEY("id"),
	UNIQUE("name"),
	CONSTRAINT "uq_group_details" UNIQUE("name","year","major")
);
CREATE TABLE IF NOT EXISTS "Schedules" (
	"id"	INTEGER NOT NULL,
	"course_id"	INTEGER,
	"room_number"	VARCHAR NOT NULL,
	"group_id"	INTEGER,
	"day_of_week"	INTEGER,
	"start_time"	VARCHAR NOT NULL,
	"end_time"	VARCHAR NOT NULL,
	"subgroup"	VARCHAR,
	"week_parity"	VARCHAR NOT NULL,
	"start_date"	DATE NOT NULL,
	"end_date"	DATE NOT NULL,
	"teacher_id"	INTEGER,
	PRIMARY KEY("id"),
	FOREIGN KEY("course_id") REFERENCES "Courses"("id"),
	FOREIGN KEY("group_id") REFERENCES "Groups"("id"),
	FOREIGN KEY("teacher_id") REFERENCES "Teachers"("id")
);
CREATE TABLE IF NOT EXISTS "Students" (
	"student_id"	INTEGER NOT NULL,
	"faculty_number"	VARCHAR NOT NULL,
	"rfid_uid"	VARCHAR NOT NULL,
	"name"	VARCHAR NOT NULL,
	"group_id"	INTEGER,
	UNIQUE("faculty_number"),
	UNIQUE("rfid_uid"),
	PRIMARY KEY("student_id"),
	FOREIGN KEY("group_id") REFERENCES "Groups"("id")
);
CREATE TABLE IF NOT EXISTS "Teachers" (
	"id"	INTEGER NOT NULL,
	"name"	VARCHAR NOT NULL,
	"department"	VARCHAR,
	PRIMARY KEY("id")
);
CREATE TABLE IF NOT EXISTS "Users" (
	"id"	INTEGER NOT NULL,
	"username"	VARCHAR NOT NULL,
	"password_hash"	VARCHAR NOT NULL,
	"role"	VARCHAR NOT NULL,
	"linked_student_id"	INTEGER,
	"linked_teacher_id"	INTEGER,
	PRIMARY KEY("id"),
	UNIQUE("username"),
	FOREIGN KEY("linked_student_id") REFERENCES "Students"("student_id"),
	FOREIGN KEY("linked_teacher_id") REFERENCES "Teachers"("id")
);
INSERT INTO "Groups" VALUES (1,'37',1,'КСИ');
INSERT INTO "Students" VALUES (1,'12222334','1234343553','Георги Георгиев Георгиев',1);
INSERT INTO "Teachers" VALUES (1,'преподавател','Компютърнисистеми и технологии');
INSERT INTO "Users" VALUES (1,'admin','$2b$12$4SiP9sDxGT.FulzXGJpSY.g6LNz5zvQTdf.LpbgJxfATRUm.EcDc2','admin',NULL,NULL);
INSERT INTO "Users" VALUES (2,'ggeorgiev','$2b$12$UqD1BHy2zxJCKUcwQFz5LuZc7DQ4.DDNoAHWxOi9asqiAdM7SX5sq','student',1,NULL);
INSERT INTO "Users" VALUES (3,'teacher','$2b$12$OH95zSzHHyn.nXyQUQQtgOEnwhxf9MLI7KYWlgd20HYLzOLpQt5Oq','teacher',NULL,1);
COMMIT;
