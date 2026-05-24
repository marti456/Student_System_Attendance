from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from typing import List, Optional
import datetime

from models import Course, GroupCourse, Student, Schedule, Attendance
from schemas import AttendanceUpdate, CheckinIn, AttendanceOut, PaginatedAttendanceOut
from auth import get_current_user, require_role, require_any_role, get_async_session

STATUS_PRESENT = "Присъствие"
STATUS_MAKEUP  = "Отработване"
STATUS_EXCUSED = "Извинено"
ALLOWED_STATUSES = {STATUS_PRESENT, STATUS_MAKEUP, STATUS_EXCUSED}


router = APIRouter()

def get_cycle_window(
    now_date: datetime.date,
    ref_date: datetime.date | None,
    is_biweekly: bool,
) -> tuple[datetime.date, datetime.date]:
    """Пресмята началото и края на текущия учебен цикъл."""
    if is_biweekly and ref_date:
        weeks_delta = (now_date - ref_date).days // 7
        cycle_start = ref_date + datetime.timedelta(weeks=(weeks_delta // 2) * 2)
        cycle_end   = cycle_start + datetime.timedelta(days=14)
    else:
        # Седмичен — текущата календарна седмица (Пон → Нед)
        cycle_start = now_date - datetime.timedelta(days=now_date.weekday())
        cycle_end   = cycle_start + datetime.timedelta(days=7)
    return cycle_start, cycle_end


async def find_schedule_in_room(
    db: AsyncSession,
    room_number: str,
    now_date: datetime.date,
    now_time: datetime.time,
    student_group_id: int,
) -> tuple[Schedule | None, Schedule | None]:
    """
    Търси активен график в залата в момента.
    Връща (собствен_график, гост_график).
    Собственият има приоритет — ако се намери, гост не се търси повече.
    """
    stmt = (
        select(Schedule)
        .options(joinedload(Schedule.group_course))
        .where(and_(
            Schedule.room_number  == room_number,
            Schedule.day_of_week  == now_date.weekday(),
            Schedule.start_date   <= now_date,
            Schedule.end_date     >= now_date,
            Schedule.start_time   <= now_time,
            Schedule.end_time     >  now_time,
        ))
    )
    schedules = (await db.execute(stmt)).scalars().all()

    matched = None
    guest   = None
    for sched in schedules:
        if sched.is_biweekly:
            weeks_delta = (now_date - sched.start_date).days // 7
            if weeks_delta % 2 != 0:
                continue  # не е активна седмица за този график

        if sched.group_course.group_id == student_group_id:
            matched = sched
            break           # собствената група — по-нататък не търсим
        elif guest is None:
            guest = sched   # пазим само първия намерен гост

    return matched, guest


async def get_biweekly_ref_date(
    db: AsyncSession,
    group_id: int,
    course_id: int,
    course_type: str,
) -> datetime.date | None:
    """
    Връща най-ранния start_date на biweekly график за
    дадена група + предмет + тип. Нужен за консистентен цикъл
    при отработване с чужда група/подгрупа.
    """
    stmt = (
        select(Schedule.start_date)
        .join(GroupCourse, Schedule.group_course_id == GroupCourse.id)
        .where(and_(
            GroupCourse.group_id == group_id,
            GroupCourse.course_id == course_id,
            GroupCourse.type     == course_type,
            Schedule.is_biweekly == True,
        ))
        .order_by(Schedule.start_date.asc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.post("/checkin")
async def checkin(payload: CheckinIn, db: AsyncSession = Depends(get_async_session)):
    # 1. Студент по RFID
    student = (await db.execute(
        select(Student).where(Student.rfid_uid == payload.rfid_uid)
    )).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Невалиден RFID.")

    now      = datetime.datetime.now()
    now_date = now.date()
    now_time = now.time()

    # 2. Намиране на активен график
    matched, guest = await find_schedule_in_room(
        db, payload.room_number, now_date, now_time, student.group_id
    )

    # 3. Валидация при отработване с чужда група
    if guest and not matched:
        valid = (await db.execute(
            select(GroupCourse).where(and_(
                GroupCourse.group_id  == student.group_id,
                GroupCourse.course_id == guest.group_course.course_id,
                GroupCourse.type      == guest.group_course.type,
            ))
        )).scalar_one_or_none()
        if not valid:
            raise HTTPException(status_code=403, detail="Нямате това занятие в учебния си план.")
        matched = guest

    if not matched:
        raise HTTPException(status_code=404, detail="В момента няма активно занятие в тази зала.")

    # 4. Референтна дата за цикъла (само при biweekly)
    ref_date = None
    if matched.is_biweekly:
        ref_date = await get_biweekly_ref_date(
            db, student.group_id,
            matched.group_course.course_id,
            matched.group_course.type,
        ) or matched.start_date  # fallback — не би трябвало да се случи

    # 5. Проверка за дублиране в рамките на цикъла
    cycle_start, cycle_end = get_cycle_window(now_date, ref_date, matched.is_biweekly)
    cycle_start_dt = datetime.datetime.combine(cycle_start, datetime.time.min)
    cycle_end_dt   = datetime.datetime.combine(cycle_end,   datetime.time.min)

    already = (await db.execute(
        select(Attendance)
        .join(Schedule,    Attendance.schedule_id    == Schedule.id)
        .join(GroupCourse, Schedule.group_course_id  == GroupCourse.id)
        .where(and_(
            Attendance.student_id   == student.student_id,
            GroupCourse.course_id   == matched.group_course.course_id,
            GroupCourse.type        == matched.group_course.type,
            Attendance.timestamp    >= cycle_start_dt,
            Attendance.timestamp    <  cycle_end_dt,
        ))
    )).scalars().first()
    if already:
        raise HTTPException(status_code=403, detail="Вече сте се отчели за този предмет в текущия учебен цикъл.")

    # 6. Запис
    status = STATUS_PRESENT if student.group_id == matched.group_course.group_id else STATUS_MAKEUP
    db.add(Attendance(
        student_id  = student.student_id,
        schedule_id = matched.id,
        timestamp   = now,
        status      = status,
        recorded_by = "Автоматичен",
    ))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Грешка при запис.")

    return {"detail": f"Успешно: {status}", "status": status}
    

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
async def add_attendance(
    student_id: int,
    schedule_id: int,
    status: str,
    date: str,
    db: AsyncSession = Depends(get_async_session),
    current_user = Depends(get_current_user)
):
    # 1. Валидация на статуса
    if status not in ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Невалиден статус. Позволени стойности: {', '.join(ALLOWED_STATUSES)}"
        )

    # 2. Валидация на студента
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен.")

    # 3. Валидация на разписанието
    res_sched = await db.execute(
        select(Schedule)
        .options(joinedload(Schedule.group_course))
        .where(Schedule.id == schedule_id)
    )
    sched = res_sched.scalar_one_or_none()
    if not sched:
        raise HTTPException(status_code=404, detail="Разписанието не е намерено.")

    # 4. Проверка на права за учител
    if current_user.role == "teacher":
        if sched.group_course.teacher_id != current_user.linked_teacher_id:
            raise HTTPException(status_code=403, detail="Нямате права да добавяте присъствия за този предмет.")

    # 5. Парсиране на датата
    try:
        target_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалиден формат на датата. Очакван: YYYY-MM-DD")

    # 6. Проверка за дублиране в рамките на избрания ден
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
        raise HTTPException(
            status_code=400,
            detail=f"Студентът вече има присъствие за това занятие на дата {date}."
        )

    # 7. Запис
    att = Attendance(
        student_id  = student_id,
        schedule_id = schedule_id,
        timestamp   = datetime.datetime.combine(target_date, sched.start_time),
        status      = status,
        recorded_by = current_user.username,
    )
    db.add(att)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Грешка при запис в базата данни.")

    return {"detail": "Присъствието е добавено успешно."}

@router.patch("/attendance/{att_id}", dependencies=[Depends(require_any_role(["teacher", "admin"]))])
async def update_attendance(
    att_id: int,
    payload: AttendanceUpdate,
    db: AsyncSession = Depends(get_async_session),
    current_user = Depends(get_current_user)
):
    # 1. Намиране на записа
    res = await db.execute(select(Attendance).where(Attendance.id == att_id))
    att = res.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Записът не е намерен.")

    # 2. Проверка на права за учител
    if current_user.role == "teacher":
        # 2а. Дали учителят преподава този предмет
        res_sched = await db.execute(
            select(Schedule)
            .options(joinedload(Schedule.group_course))
            .where(Schedule.id == att.schedule_id)
        )
        sched = res_sched.scalar_one_or_none()
        if not sched or sched.group_course.teacher_id != current_user.linked_teacher_id:
            raise HTTPException(status_code=403, detail="Нямате права да редактирате запис за този предмет.")

        # 2б. Учителят не може да редактира записи въведени от администратор
        if att.recorded_by != "Автоматичен" and att.recorded_by != current_user.username:
            raise HTTPException(status_code=403, detail="Нямате права да редактирате запис на администратор.")

    # 3. Валидация на новия статус
    if payload.status is not None:
        if payload.status not in ALLOWED_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Невалиден статус. Позволени стойности: {', '.join(ALLOWED_STATUSES)}"
            )
        att.status = payload.status

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Грешка при запис в базата данни.")

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
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Грешка при изтриване от базата данни.")
    return {"detail": "Записът е изтрит."}
