from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import List
import datetime

from models import GroupCourse, Student, Schedule, Attendance, AsyncSessionLocal
from schemas import CheckinIn, AttendanceOut
from auth import get_current_user, require_role, require_any_role, get_async_session

router = APIRouter()

def get_cycle_window(now_date: datetime.date, schedule_start_date: datetime.date, is_biweekly: bool):
    # Колко дни са минали от първото реално занятие за този предмет
    delta = now_date - schedule_start_date
    days_since_start = max(0, delta.days) 
    
    if is_biweekly:
        # 14-дневен цикъл
        cycle_index = days_since_start // 14
        cycle_start = schedule_start_date + datetime.timedelta(days=cycle_index * 14)
        cycle_end = cycle_start + datetime.timedelta(days=14)
    else:
        # 7-дневен цикъл
        cycle_index = days_since_start // 7
        cycle_start = schedule_start_date + datetime.timedelta(days=cycle_index * 7)
        cycle_end = cycle_start + datetime.timedelta(days=7)
        
    return cycle_start, cycle_end

# Helper: find current schedule by room and current time
# def _time_matches(slot_start: str, slot_end: str, now_time: datetime.time) -> bool:
#     start = datetime.time(int(slot_start.split(":")[0]), int(slot_start.split(":")[1]))
#     end = datetime.time(int(slot_end.split(":")[0]), int(slot_end.split(":")[1]))
#     return start <= now_time <= end

@router.post("/checkin")
async def checkin(payload: CheckinIn, db: AsyncSession = Depends(get_async_session), api_key: str = None):
    # Note: for ESP32 protect with API key or use device JWT. Here it's open — add protection!
    # 1. Намиране на студента по RFID
    res = await db.execute(select(Student).where(Student.rfid_uid == payload.rfid_uid))
    student = res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Невалиден RFID")

    now = datetime.datetime.now()
    now_date = now.date()
    now_time = now.time()
    now_weekday = now.weekday() # 0 = Понеделник, 6 = Неделя
    # 2. Намираме кое разписание тече в момента в тази зала
    res_sched = await db.execute(
        select(Schedule)
        .options(joinedload(Schedule.group_course))
        .where(
            and_(
                Schedule.room_number == payload.room_number,
                Schedule.day_of_week == now_weekday
            )
        )
    )
    schedules = res_sched.scalars().all()
    
    matched_schedule = None
    for sched in schedules:
        if sched.start_time <= now_time <= sched.end_time:
            matched_schedule = sched
            break
            
    if not matched_schedule:
        raise HTTPException(status_code=404, detail="В момента няма активно занятие в тази зала.")
    
    # 3. ЗАЩИТА: Дали сме в активния период на този конкретен курс?
    if not (matched_schedule.start_date <= now_date <= matched_schedule.end_date):
        raise HTTPException(
            status_code=403, 
            detail="Този курс не е активен в момента (извън зададените дати)."
        )
    
    # 4. Изчисляваме времевия прозорец за този урок (Academic Cycle)
    is_biweekly = matched_schedule.week_parity.value in ['even', 'odd']
    cycle_start, cycle_end = get_cycle_window(now_date, matched_schedule.start_date, is_biweekly)

    # Преобразуваме датите обратно в datetime за заявката към базата данни
    cycle_start_dt = datetime.datetime.combine(cycle_start, datetime.time.min)
    cycle_end_dt = datetime.datetime.combine(cycle_end, datetime.time.min)

    # 5. Проверяваме дали студентът вече има присъствие в ТОЗИ времеви прозорец за ТОЗИ предмет
    stmt = (
        select(Attendance)
        .join(Schedule, Attendance.schedule_id == Schedule.id)
        .join(GroupCourse, Schedule.group_course_id == GroupCourse.id)
        .where(
            and_(
                Attendance.student_id == student.student_id,
                GroupCourse.course_id == matched_schedule.group_course.course_id,
                Attendance.timestamp >= cycle_start_dt,
                Attendance.timestamp < cycle_end_dt
            )
        )
    )
    res_cycle_att = await db.execute(stmt)
    already_attended_in_cycle = res_cycle_att.scalars().first()

    # 6. Вземане на финално решение за статуса
    if already_attended_in_cycle:
        # Вече си е взел урока за този цикъл (напр. идва в четна и нечетна седмица едновременно)
        raise HTTPException(status_code=403, detail="Student not enrolled for this course")
    else:
        # Това му е първо идване за този учебен прозорец
        if student.group_id == matched_schedule.group_course.group_id:
            # Идва си със своята главна група
            status_text = "Присъствие"
        else:
            # Идва с чужда група (нормално отработване)
            status_text = "Отработване"

    # 7. Записване в базата
    att = Attendance(
        student_id=student.student_id, 
        schedule_id=matched_schedule.id, 
        timestamp=now, 
        status=status_text,
        recorded_by="Автоматичен"
    )
    db.add(att)
    
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Възникна грешка при запис на присъствието.")
    
    return {"detail": f"Успешно регистрирано: {status_text}", "status": status_text}

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
        res = await db.execute(
            select(Schedule)
            .options(joinedload(Schedule.group_course)) # ДОБАВЕНО
            .where(Schedule.id == schedule_id)
        )
        sched = res.scalar_one_or_none()
        if not sched or sched.group_course.teacher_id != current_user.linked_teacher_id:
            raise HTTPException(status_code=403, detail="Not allowed for this schedule")
    # insert
    att = Attendance(student_id=student_id, schedule_id=schedule_id, timestamp=datetime.datetime.now(), status=status, recorded_by=current_user.username)
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
        res = await db.execute(
            select(Schedule)
            .options(joinedload(Schedule.group_course)) # ДОБАВЕНО
            .where(Schedule.id == att.schedule_id)
        )
        sched = res.scalar_one_or_none()
        if not sched or sched.group_course.teacher_id != current_user.linked_teacher_id:
            raise HTTPException(status_code=403, detail="Not allowed to delete this record")
    await db.delete(att)
    await db.commit()
    return {"detail": "Deleted"}
