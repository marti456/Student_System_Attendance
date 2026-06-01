import hashlib
import hmac as hmac_lib
import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from models import Course, GroupCourse, Student, Schedule, Attendance
from schemas import AttendanceUpdate, CheckinIn, AttendanceOut, PaginatedAttendanceOut
from auth import get_current_user, require_any_role, get_async_session

router = APIRouter()


def _verify_hmac(hmac_key_hex: str, faculty_number: str, atc: int, signature: str) -> bool:
    """HMAC-SHA256 верификация — идентична с изчислението в Android приложението."""
    key_bytes = bytes.fromhex(hmac_key_hex)
    message   = f"{faculty_number}|{atc}".encode("utf-8")
    expected  = hmac_lib.new(key_bytes, message, hashlib.sha256).hexdigest()
    # compare_digest предотвратява timing атаки
    return hmac_lib.compare_digest(expected, signature.lower())


@router.post("/checkin")
async def checkin(payload: CheckinIn, db: AsyncSession = Depends(get_async_session)):
    """
    Endpoint, извикван от ESP32 след успешен NFC прочит на Android телефон.

    Очакван payload формат: "ФАКТ_НОМ|ATC|HMAC_HEX"
    Пример: "2301234|42|a3f9bc1d..."
    """
    # 1. Парсиране на payload-а
    try:
        parts = payload.payload.strip().split("|")
        if len(parts) != 3:
            raise ValueError("Очаквани са точно 3 части.")
        faculty_number, atc_str, signature = parts
        atc = int(atc_str)
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=400,
            detail="Невалиден формат на NFC payload. Очакван: 'ФН|ATC|HMAC'."
        )

    # 2. Намиране на студента по факултетен номер
    res = await db.execute(select(Student).where(Student.faculty_number == faculty_number))
    student = res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен.")

    if not student.hmac_key:
        raise HTTPException(
            status_code=403,
            detail="Няма регистриран NFC ключ. Влезте в приложението за да получите ключ."
        )

    # 3. Replay защита — ATC трябва да е строго по-голям от последния записан
    if atc <= student.atc_counter:
        raise HTTPException(
            status_code=403,
            detail=f"Невалиден ATC ({atc} ≤ {student.atc_counter}). Повторно изпращане?"
        )

    # 4. Верификация на HMAC подписа
    if not _verify_hmac(student.hmac_key, faculty_number, atc, signature):
        raise HTTPException(status_code=403, detail="Невалиден криптографски подпис.")

    # 5. Обновяване на ATC брояча (преди да запишем присъствието)
    student.atc_counter = atc

    # 6. Намиране на активния график в тази зала
    now      = datetime.datetime.now()
    now_date = now.date()
    now_time = now.time()

    stmt = (
        select(Schedule)
        .options(joinedload(Schedule.group_course))
        .where(
            and_(
                Schedule.room_number == payload.room_number,
                Schedule.day_of_week == now_date.weekday(),
                Schedule.start_date  <= now_date,
                Schedule.end_date    >= now_date,
                Schedule.start_time  <= now_time,
                Schedule.end_time    >  now_time,
            )
        )
        .order_by(Schedule.start_date.asc())
    )
    res_sched  = await db.execute(stmt)
    schedules  = res_sched.scalars().all()

    matched_schedule = None
    guest_schedule   = None

    for sched in schedules:
        if sched.is_biweekly:
            weeks_delta = (now_date - sched.start_date).days // 7
            if weeks_delta % 2 != 0:
                continue
        if sched.group_course.group_id == student.group_id:
            matched_schedule = sched
            break
        else:
            guest_schedule = sched

    if guest_schedule and not matched_schedule:
        matched_schedule = guest_schedule  # Отработване в чужда група

    if not matched_schedule:
        raise HTTPException(status_code=404, detail="В момента няма активно занятие в тази зала.")

    # 7. Проверка за дублиране за СЪЩИЯ предмет и тип днес
    stmt_dup = (
        select(Attendance)
        .join(Schedule,    Attendance.schedule_id == Schedule.id)
        .join(GroupCourse, Schedule.group_course_id == GroupCourse.id)
        .where(
            and_(
                Attendance.student_id  == student.student_id,
                GroupCourse.course_id  == matched_schedule.group_course.course_id,
                GroupCourse.type       == matched_schedule.group_course.type,
                func.date(Attendance.timestamp) == now_date,
            )
        )
    )
    if (await db.execute(stmt_dup)).scalars().first():
        raise HTTPException(status_code=403, detail="Вече сте се отчели за този урок днес.")

    # 8. Записване на присъствието
    status_text = (
        "Присъствие"
        if student.group_id == matched_schedule.group_course.group_id
        else "Отработване"
    )
    att = Attendance(
        student_id  = student.student_id,
        schedule_id = matched_schedule.id,
        timestamp   = now,
        status      = status_text,
        recorded_by = "Автоматичен",
    )
    db.add(att)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Грешка при запис в базата данни.")

    return {"detail": f"Успешно: {status_text}", "status": status_text}


# ──────────────────────────────────────────────────────────────
# Останалите endpoints (ръчно отчитане, списък, редакция, изтриване)
# са непроменени спрямо оригинала.
# ──────────────────────────────────────────────────────────────

@router.get("/attendance", response_model=PaginatedAttendanceOut)
async def list_attendance(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session),
    current_user = Depends(get_current_user),
):
    stmt = (
        select(
            Attendance.id,
            Attendance.timestamp,
            Attendance.status,
            Attendance.recorded_by,
            Student.name.label("student_name"),
            Student.faculty_number,
            Course.name.label("course_name"),
            GroupCourse.type.label("course_type"),
        )
        .join(Student,    Attendance.student_id == Student.student_id)
        .join(Schedule,   Attendance.schedule_id == Schedule.id)
        .join(GroupCourse, Schedule.group_course_id == GroupCourse.id)
        .join(Course,     GroupCourse.course_id == Course.id)
    )

    if current_user.role == "student":
        stmt = stmt.where(Attendance.student_id == current_user.linked_student_id)

    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            or_(Student.name.ilike(term), Student.faculty_number.ilike(term))
        )

    count_stmt  = select(func.count()).select_from(stmt.subquery())
    total_count = (await db.execute(count_stmt)).scalar()

    stmt = stmt.order_by(Attendance.timestamp.desc()).offset(skip).limit(limit)
    rows = (await db.execute(stmt)).all()

    type_map = {"lecture": "Лекция", "exercise": "Упражнение", "lab": "Лаб."}
    items = [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "status": r.status,
            "recorded_by": r.recorded_by,
            "student_name": f"{r.student_name} (ФН: {r.faculty_number})",
            "course_name": f"{r.course_name} ({type_map.get(r.course_type, r.course_type)})",
        }
        for r in rows
    ]
    return {"total": total_count, "items": items}


@router.post("/attendance", dependencies=[Depends(require_any_role(["teacher", "admin"]))])
async def add_attendance(
    student_id: int,
    schedule_id: int,
    status: str,
    date: str,
    db: AsyncSession = Depends(get_async_session),
    current_user = Depends(get_current_user),
):
    res_sched = await db.execute(
        select(Schedule).options(joinedload(Schedule.group_course)).where(Schedule.id == schedule_id)
    )
    sched = res_sched.scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Разписанието не е намерено.")

    if current_user.role == "teacher":
        if sched.group_course.teacher_id != current_user.linked_teacher_id:
            raise HTTPException(status_code=403, detail="Нямате права за този предмет.")

    try:
        target_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалиден формат на датата.")

    target_timestamp = datetime.datetime.combine(target_date, sched.start_time)
    day_start = datetime.datetime.combine(target_date, datetime.time.min)
    day_end   = datetime.datetime.combine(target_date, datetime.time.max)

    existing = await db.execute(
        select(Attendance).where(
            and_(
                Attendance.student_id  == student_id,
                Attendance.schedule_id == schedule_id,
                Attendance.timestamp   >= day_start,
                Attendance.timestamp   <= day_end,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Студентът вече има присъствие на {date}.")

    att = Attendance(
        student_id  = student_id,
        schedule_id = schedule_id,
        timestamp   = target_timestamp,
        status      = status,
        recorded_by = current_user.username,
    )
    db.add(att)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Грешка при запис.")

    return {"detail": "Присъствието е добавено успешно."}


@router.patch("/attendance/{att_id}", dependencies=[Depends(require_any_role(["teacher", "admin"]))])
async def update_attendance(
    att_id: int,
    payload: AttendanceUpdate,
    db: AsyncSession = Depends(get_async_session),
    current_user = Depends(get_current_user),
):
    res = await db.execute(select(Attendance).where(Attendance.id == att_id))
    att = res.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Записът не е намерен.")

    if current_user.role == "teacher":
        if att.recorded_by not in ("Автоматичен", current_user.username):
            raise HTTPException(status_code=403, detail="Нямате права да редактирате този запис.")

    if payload.status:
        att.status = payload.status

    await db.commit()
    return {"detail": "Статусът е променен."}


@router.delete("/attendance/{att_id}", dependencies=[Depends(require_any_role(["teacher", "admin"]))])
async def delete_attendance(
    att_id: int,
    db: AsyncSession = Depends(get_async_session),
    current_user = Depends(get_current_user),
):
    res = await db.execute(select(Attendance).where(Attendance.id == att_id))
    att = res.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Не е намерено.")

    if current_user.role == "teacher":
        res_sched = await db.execute(
            select(Schedule).options(joinedload(Schedule.group_course)).where(Schedule.id == att.schedule_id)
        )
        sched = res_sched.scalar_one_or_none()
        if not sched or sched.group_course.teacher_id != current_user.linked_teacher_id:
            raise HTTPException(status_code=403, detail="Нямате права да изтриете този запис.")
        if att.recorded_by not in ("Автоматичен", current_user.username):
            raise HTTPException(status_code=403, detail="Нямате права да изтривате записи на администратор.")

    await db.delete(att)
    await db.commit()
    return {"detail": "Записът е изтрит."}