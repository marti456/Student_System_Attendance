from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
import datetime


# ──────────────────── AUTH / ПОТРЕБИТЕЛИ ────────────────────

class StudentRegisterIn(BaseModel):
    username: str
    password: str
    name: str
    faculty_number: str
    rfid_uid: Optional[str] = None   # Незадължително — телефонът замества картата
    group_name: str
    group_year: int
    group_major: str

class TeacherRegisterIn(BaseModel):
    username: str
    password: str
    name: str
    department: Optional[str] = None
    title: Optional[str] = None

class AdminRegisterIn(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None
    user_id: Optional[int] = None

class UserCreate(BaseModel):
    username: str
    password: str
    role: str
    linked_student_id: Optional[int] = None

class UserOut(BaseModel):
    id: int
    username: str
    role: str
    linked_student_id: Optional[int]


# ──────────────────── NFC CHECKIN ────────────────────

class CheckinIn(BaseModel):
    """
    Изпраща се от ESP32 след прочит на NFC payload от телефона.
    payload формат: "ФАКТ_НОМ|ATC|HMAC_SHA256_HEX"
    """
    payload: str = Field(..., description="Криптиран NFC payload: ФН|ATC|HMAC")
    room_number: str = Field(..., max_length=20, description="Номер на залата")


class ProvisionKeyOut(BaseModel):
    """Връща се на телефона при /auth/provision-key."""
    hmac_key: str       # 64-символен hex (32 байта)
    faculty_number: str
    atc: int            # Текущият ATC брояч в сървъра


# ──────────────────── ПРИСЪСТВИЯ ────────────────────

class AttendanceOut(BaseModel):
    id: int
    timestamp: datetime.datetime
    status: str
    recorded_by: str
    student_name: str
    course_name: str
    model_config = ConfigDict(from_attributes=True)

class AttendanceUpdate(BaseModel):
    status: Optional[str] = None

class PaginatedAttendanceOut(BaseModel):
    total: int
    items: List[AttendanceOut]


# ──────────────────── УЧЕБЕН ПЛАН ────────────────────

class CourseCreate(BaseModel):
    name: str = Field(..., max_length=150)

class CourseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)

class CourseOut(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)

class GroupCourseCreate(BaseModel):
    group_id: int
    course_id: int
    teacher_id: Optional[int] = None
    type: str = Field("lecture", description="lecture | exercise | lab")
    semester: Optional[int] = None

class GroupCourseUpdate(BaseModel):
    group_id: Optional[int] = None
    course_id: Optional[int] = None
    teacher_id: Optional[int] = None
    type: Optional[str] = None
    semester: Optional[int] = None

class GroupCourseOut(BaseModel):
    id: int
    group_id: int
    course_id: int
    teacher_id: Optional[int]
    type: str
    semester: Optional[int]
    model_config = ConfigDict(from_attributes=True)

class ScheduleCreate(BaseModel):
    group_course_id: int
    room_number: str = Field(..., max_length=20)
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: datetime.time
    end_time: datetime.time
    is_biweekly: bool = False
    start_date: datetime.date
    end_date: datetime.date
    subgroup: Optional[str] = Field(None, max_length=10)

class ScheduleUpdate(BaseModel):
    room_number: Optional[str] = Field(None, max_length=20)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    start_time: Optional[datetime.time] = None
    end_time: Optional[datetime.time] = None
    is_biweekly: Optional[bool] = None
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    subgroup: Optional[str] = Field(None, max_length=10)

class ScheduleOut(BaseModel):
    id: int
    group_course_id: int
    room_number: str
    day_of_week: int
    start_time: datetime.time
    end_time: datetime.time
    is_biweekly: bool
    start_date: datetime.date
    end_date: datetime.date
    subgroup: Optional[str]
    model_config = ConfigDict(from_attributes=True)


# ──────────────────── ГРУПИ / СТУДЕНТИ / ПРЕПОДАВАТЕЛИ ────────────────────

class GroupOut(BaseModel):
    id: int
    name: str
    year: int
    major: str
    model_config = ConfigDict(from_attributes=True)

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    year: Optional[int] = None
    major: Optional[str] = None

class StudentOut(BaseModel):
    student_id: int
    name: str
    faculty_number: str
    rfid_uid: Optional[str]   # Nullable след промяната
    group_id: int
    model_config = ConfigDict(from_attributes=True)

class StudentUpdate(BaseModel):
    name: Optional[str] = None
    faculty_number: Optional[str] = None
    rfid_uid: Optional[str] = None
    group_name: Optional[str] = None
    group_year: Optional[int] = None
    group_major: Optional[str] = None

class TeacherOut(BaseModel):
    id: int
    name: str
    title: Optional[str]
    department: Optional[str]
    model_config = ConfigDict(from_attributes=True)

class TeacherUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    department: Optional[str] = None