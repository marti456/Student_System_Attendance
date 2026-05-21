from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import datetime

from models import Student, Schedule, Attendance, AsyncSessionLocal
from schemas import CheckinIn, AttendanceOut
from auth import get_current_user, require_role, require_any_role, get_async_session

router = APIRouter()

# Helper: find current schedule by room and current time
def _time_matches(slot_start: str, slot_end: str, now_time: datetime.time) -> bool:
    start = datetime.time(int(slot_start.split(":")[0]), int(slot_start.split(":")[1]))
    end = datetime.time(int(slot_end.split(":")[0]), int(slot_end.split(":")[1]))
    return start <= now_time <= end

@router.post("/checkin")
async def checkin(payload: CheckinIn, db: AsyncSession = Depends(get_async_session), api_key: str = None):
    # Note: for ESP32 protect with API key or use device JWT. Here it's open — add protection!
    # 1. find student by rfid
    res = await db.execute(select(Student).where(Student.rfid_uid == payload.rfid_uid))
    student = res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Invalid RFID")
    # 2. find schedule for this room and current time
    now = datetime.datetime.utcnow()
    weekday = now.isoweekday()  # 1..7
    current_time = now.time().replace(second=0, microsecond=0)
    res = await db.execute(select(Schedule).where(
        and_(
            Schedule.room_number == payload.room_number,
            Schedule.day_of_week == weekday
        )
    ))
    schedules = res.scalars().all()
    matched = None
    for s in schedules:
        if _time_matches(s.start_time, s.end_time, current_time):
            matched = s
            break
    if not matched:
        raise HTTPException(status_code=404, detail="No scheduled class right now in this room")
    # 3. check duplicate
    res = await db.execute(select(Attendance).where(
        and_(Attendance.student_id == student.student_id, Attendance.schedule_id == matched.id)
    ))
    if res.scalar_one_or_none():
        return {"detail": "Already checked in"}
    # 4. determine status
    status_text = "Присъствие" if student.group_id == matched.group_id else None
    if status_text is None:
        # check if student's group has this course elsewhere
        res = await db.execute(select(Schedule).where(
            and_(Schedule.group_id == student.group_id, Schedule.course_id == matched.course_id)
        ))
        if res.scalar_one_or_none():
            status_text = "Отработване"
        else:
            raise HTTPException(status_code=403, detail="Student not enrolled for this course")
    # 5. insert attendance
    att = Attendance(student_id=student.student_id, schedule_id=matched.id, timestamp=datetime.datetime.utcnow(), status=status_text)
    db.add(att)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="DB error")
    return {"detail": f"SUCCESS: {status_text}"}

# GET attendance - students see only their own
@router.get("/attendance", response_model=List[AttendanceOut])
async def list_attendance(db: AsyncSession = Depends(get_async_session), current_user = Depends(get_current_user)):
    # student -> linked_student_id must exist and only their records
    if current_user.role == "student":
        if not current_user.linked_student_id:
            raise HTTPException(status_code=400, detail="Student user not linked to student record")
        res = await db.execute(select(Attendance).where(Attendance.student_id == current_user.linked_student_id))
    else:
        res = await db.execute(select(Attendance).order_by(Attendance.timestamp.desc()))
    rows = res.scalars().all()
    return rows

# teacher/admin add attendance manually
@router.post("/attendance", dependencies=[Depends(require_any_role(["teacher"]))])
async def add_attendance(student_id: int, schedule_id: int, status: str, db: AsyncSession = Depends(get_async_session), current_user = Depends(get_current_user)):
    # teacher can only add for schedules they teach (unless admin)
    if current_user.role == "teacher":
        res = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
        sched = res.scalar_one_or_none()
        if not sched or sched.teacher_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not allowed for this schedule")
    # insert
    att = Attendance(student_id=student_id, schedule_id=schedule_id, timestamp=datetime.datetime.utcnow(), status=status)
    db.add(att)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Could not insert (maybe duplicate)")
    return {"detail": "Inserted"}

# delete attendance
@router.delete("/attendance/{att_id}", dependencies=[Depends(require_any_role(["teacher"]))])
async def delete_attendance(att_id: int, db: AsyncSession = Depends(get_async_session), current_user = Depends(get_current_user)):
    res = await db.execute(select(Attendance).where(Attendance.id == att_id))
    att = res.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Not found")
    # teacher can only delete for schedules they teach
    if current_user.role == "teacher":
        res = await db.execute(select(Schedule).where(Schedule.id == att.schedule_id))
        sched = res.scalar_one_or_none()
        if not sched or sched.teacher_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not allowed to delete this record")
    await db.delete(att)
    await db.commit()
    return {"detail": "Deleted"}
