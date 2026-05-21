from sqlalchemy import (
    Column, Integer, String, ForeignKey, UniqueConstraint, DateTime, Text
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import datetime
from passlib.context import CryptContext
from typing import Optional

Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class Group(Base):
    __tablename__ = "Groups"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

class Course(Base):
    __tablename__ = "Courses"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

class Student(Base):
    __tablename__ = "Students"
    student_id = Column(Integer, primary_key=True)
    rfid_uid = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    group_id = Column(Integer, ForeignKey("Groups.id"))
    group = relationship("Group")

class User(Base):
    __tablename__ = "Users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # student/teacher/admin
    linked_student_id = Column(Integer, ForeignKey("Students.student_id"), nullable=True)
    linked_student = relationship("Student")

    def verify_password(self, password: str) -> bool:
        return pwd_context.verify(password, self.password_hash)

    @classmethod
    def hash_password(cls, password: str) -> str:
        return pwd_context.hash(password)

class Schedule(Base):
    __tablename__ = "Schedules"
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("Courses.id"))
    room_number = Column(String, nullable=False)
    group_id = Column(Integer, ForeignKey("Groups.id"))
    day_of_week = Column(Integer)
    start_time = Column(String, nullable=False)  # "HH:MM"
    end_time = Column(String, nullable=False)
    teacher_id = Column(Integer, ForeignKey("Users.id"), nullable=True)

class Attendance(Base):
    __tablename__ = "Attendance"
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("Students.student_id"))
    schedule_id = Column(Integer, ForeignKey("Schedules.id"))
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("student_id", "schedule_id", name="uq_student_schedule"),)

# Async engine URL for sqlite
engine_url = "sqlite+aiosqlite:///./attendance.db"
async_engine = create_async_engine(engine_url, future=True, echo=False)
AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

async def init_models(session_factory):
    async with session_factory() as db:
        # seed basic admin if not present
        from sqlalchemy import select
        res = await db.execute(select(User).where(User.username == "admin"))
        admin = res.scalar_one_or_none()
        if not admin:
            admin = User(username="admin", password_hash=User.hash_password("admin123"), role="admin")
            db.add(admin)
            await db.commit()
