from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import List, Optional
import datetime

from models import Course, GroupCourse, Student, Schedule, Attendance, AsyncSessionLocal
from schemas import AttendanceUpdate, CheckinIn, AttendanceOut, PaginatedAttendanceOut
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
@router.get("/attendance", response_model=PaginatedAttendanceOut)
async def list_attendance(
    skip: int = 0, 
    limit: int = 50, 
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_async_session), 
    current_user = Depends(get_current_user)
):
    # 1. Подготвяме базовата заявка с всички JOIN-ове
    stmt = (
        select(
            Attendance.id, 
            Attendance.timestamp, 
            Attendance.status, 
            Attendance.recorded_by,
            Student.name.label("student_name"),
            Student.faculty_number,
            Course.name.label("course_name"),
            GroupCourse.type.label("course_type")
        )
        .join(Student, Attendance.student_id == Student.student_id)
        .join(Schedule, Attendance.schedule_id == Schedule.id)
        .join(GroupCourse, Schedule.group_course_id == GroupCourse.id)
        .join(Course, GroupCourse.course_id == Course.id)
    )

    # 2. Филтрираме по роля (ако е студент, вижда само своите)
    if current_user.role == "student":
        stmt = stmt.where(Attendance.student_id == current_user.linked_student_id)

    # 3. УМНО ТЪРСЕНЕ: Търсим по Име ИЛИ по Факултетен номер
    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                Student.name.ilike(search_term),
                Student.faculty_number.ilike(search_term)
            )
        )

    # 4. Вземаме ОБЩИЯ брой на записите (преди да отрежем 50-те бройки)
    # Това е нужно, за да може фронтендът да нарисува бутоните за страници
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_res = await db.execute(count_stmt)
    total_count = total_res.scalar()

    # 5. Прилагаме сортиране, странициране (OFFSET) и лимит (LIMIT)
    stmt = stmt.order_by(Attendance.timestamp.desc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    rows = res.all()
    
    # 6. Форматираме резултата
    type_map = {'lecture': 'Лекция', 'exercise': 'Упражнение', 'lab': 'Лаб.'}
    items = []
    for row in rows:
        items.append({
            "id": row.id,
            "timestamp": row.timestamp.isoformat(),
            "status": row.status,
            "recorded_by": row.recorded_by,
            "student_name": f"{row.student_name} (ФН: {row.faculty_number})",
            "course_name": f"{row.course_name} ({type_map.get(row.course_type, row.course_type)})"
        })
        
    return {"total": total_count, "items": items}

# teacher/admin add attendance manually
@router.post("/attendance", dependencies=[Depends(require_any_role(["teacher", "admin"]))])
async def add_attendance(student_id: int, schedule_id: int, status: str, date: str, db: AsyncSession = Depends(get_async_session), current_user = Depends(get_current_user)):
    
    # 1. Извличаме разписанието
    res_sched = await db.execute(select(Schedule).options(joinedload(Schedule.group_course)).where(Schedule.id == schedule_id))
    sched = res_sched.scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Разписанието не е намерено.")
        
    if current_user.role == "teacher":
        if sched.group_course.teacher_id != current_user.linked_teacher_id:
            raise HTTPException(status_code=403, detail="Нямате права да добавяте присъствия за този предмет.")
            
    # 2. Парсираме датата от фронтенда (очакваме формат "YYYY-MM-DD")
    try:
        target_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалиден формат на датата.")

    # 3. Създаваме точния времеви печат (Избраната дата + Началния час по график)
    target_timestamp = datetime.datetime.combine(target_date, sched.start_time)
    
    # 4. Проверка за дублиране в РАМКИТЕ НА ИЗБРАНИЯ ДЕН
    day_start = datetime.datetime.combine(target_date, datetime.time.min)
    day_end = datetime.datetime.combine(target_date, datetime.time.max)
    
    stmt_duplicate = select(Attendance).where(
        and_(
            Attendance.student_id == student_id,
            Attendance.schedule_id == schedule_id,
            Attendance.timestamp >= day_start,
            Attendance.timestamp <= day_end
        )
    )
    existing = await db.execute(stmt_duplicate)
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Студентът вече има присъствие за това занятие на дата {date}.")

    # 5. Записване в базата
    att = Attendance(
        student_id=student_id, 
        schedule_id=schedule_id, 
        timestamp=target_timestamp, 
        status=status, 
        recorded_by=current_user.username
    )
    db.add(att)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Грешка при запис в базата данни.")
        
    return {"detail": "Присъствието е добавено успешно."}

@router.patch("/attendance/{att_id}", dependencies=[Depends(require_any_role(["teacher", "admin"]))])
async def update_attendance(att_id: int, payload: AttendanceUpdate, db: AsyncSession = Depends(get_async_session), current_user = Depends(get_current_user)):
    res = await db.execute(select(Attendance).where(Attendance.id == att_id))
    att = res.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Записът не е намерен.")
        
    if current_user.role == "teacher":
        if att.recorded_by != "Автоматичен" and att.recorded_by != current_user.username:
            raise HTTPException(status_code=403, detail="Нямате права да редактирате запис на администратор.")
            
    if payload.status:
        att.status = payload.status
        
    await db.commit()
    return {"detail": "Статусът на присъствието е променен."}

# delete attendance
@router.delete("/attendance/{att_id}", dependencies=[Depends(require_any_role(["teacher", "admin"]))])
async def delete_attendance(att_id: int, db: AsyncSession = Depends(get_async_session), current_user = Depends(get_current_user)):
    res = await db.execute(select(Attendance).where(Attendance.id == att_id))
    att = res.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Не е намерено.")
        
    if current_user.role == "teacher":
        # 1. Проверка дали преподавателят води този предмет
        res_sched = await db.execute(select(Schedule).options(joinedload(Schedule.group_course)).where(Schedule.id == att.schedule_id))
        sched = res_sched.scalar_one_or_none()
        if not sched or sched.group_course.teacher_id != current_user.linked_teacher_id:
            raise HTTPException(status_code=403, detail="Нямате права да изтриете този запис.")
            
        # НОВО: 2. Проверка кой го е въвел (Учителят не може да трие записи на Админа)
        if att.recorded_by != "Автоматичен" and att.recorded_by != current_user.username:
            raise HTTPException(
                status_code=403, 
                detail="Нямате права да изтривате запис, въведен от администратор или друг служител."
            )
            
    await db.delete(att)
    await db.commit()
    return {"detail": "Записът е изтрит."}
