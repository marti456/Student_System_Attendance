from pydantic import BaseModel
from typing import Optional
import datetime

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

class CheckinIn(BaseModel):
    rfid_uid: str
    room_number: str

class AttendanceOut(BaseModel):
    id: int
    student_id: int
    schedule_id: int
    timestamp: datetime.datetime
    status: str
