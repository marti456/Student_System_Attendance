import enum

from sqlalchemy import (
    CheckConstraint, Column, Date, Index, Integer, String, ForeignKey, Time, UniqueConstraint, DateTime, Text
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import datetime
from passlib.context import CryptContext

Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class WeekParity(str, enum.Enum):
    ALL = "all"
    ODD = "odd"
    EVEN = "even"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"


class Group(Base):
    __tablename__ = "Groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    year = Column(Integer, nullable=False)
    major = Column(String(100), nullable=False)
    __table_args__ = (
        UniqueConstraint("name", "year", "major", name="uq_group_details"),
        CheckConstraint("year >= 1 AND year <= 5", name="ck_group_year"),
    )
    students = relationship("Student", back_populates="group")


class Course(Base):
    __tablename__ = "Courses"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), unique=True, nullable=False)


class GroupCourse(Base):
    __tablename__ = "GroupCourses"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("Groups.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("Courses.id"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("Teachers.id"), nullable=True)
    type = Column(String(20), nullable=False, default="lecture")   # lecture, exercise, lab
    semester = Column(Integer, nullable=True)
    group = relationship("Group")
    course = relationship("Course")
    teacher = relationship("Teacher")
    __table_args__ = (
        UniqueConstraint("group_id", "course_id", "type", name="uq_group_course_type"),
    )


class Student(Base):
    __tablename__ = "Students"
    student_id = Column(Integer, primary_key=True, autoincrement=True)
    faculty_number = Column(String(20), unique=True, nullable=False)
    rfid_uid = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    group_id = Column(Integer, ForeignKey("Groups.id"), nullable=False)
    group = relationship("Group", back_populates="students")


class Teacher(Base):
    __tablename__ = "Teachers"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    title = Column(String(50), nullable=True)
    department = Column(String(100), nullable=True)

class User(Base):
    __tablename__ = "Users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # student / teacher / admin
    linked_student_id = Column(Integer, ForeignKey("Students.student_id"), nullable=True)
    linked_student = relationship("Student")
    linked_teacher_id = Column(Integer, ForeignKey("Teachers.id"), nullable=True)
    linked_teacher = relationship("Teacher")
    def verify_password(self, password: str) -> bool:
        return pwd_context.verify(password, self.password_hash)
    @classmethod
    def hash_password(cls, password: str) -> str:
        return pwd_context.hash(password)

class Schedule(Base):
    __tablename__ = "Schedules"
    id = Column(Integer, primary_key=True)
    group_course_id = Column(Integer, ForeignKey("GroupCourses.id"), nullable=False)
    room_number = Column(String(20), nullable=False)
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    week_parity = Column(String(10), nullable=False, default="all")   # SQLite-friendly
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    subgroup = Column(String(10), nullable=True)
    group_course = relationship("GroupCourse")
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_day_of_week"),
        CheckConstraint("start_time < end_time", name="ck_time_order"),
        UniqueConstraint("group_course_id", "day_of_week", "start_time", "week_parity", "subgroup",
                         name="uq_schedule_slot"),
    )


class Attendance(Base):
    __tablename__ = "Attendance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("Students.student_id"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("Schedules.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.now, nullable=False)
    status = Column(String(20), nullable=False, default="present")
    recorded_by = Column(String(50), nullable=False, default="Автоматичен")
    student = relationship("Student")
    schedule = relationship("Schedule")



engine_url = "sqlite+aiosqlite:///./attendance.db"
async_engine = create_async_engine(engine_url, future=True, echo=False)
AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

async def init_models(session_factory):
    async with session_factory() as db:
        from sqlalchemy import select
        res = await db.execute(select(User).where(User.username == "admin"))
        admin = res.scalar_one_or_none()
        if not admin:
            admin = User(username="admin", password_hash=User.hash_password("admin123"), role="admin")
            db.add(admin)
            await db.commit()