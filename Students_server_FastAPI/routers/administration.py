from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
from models import Course, GroupCourse, Schedule, Teacher, Group
from schemas import CourseCreate, CourseOut, GroupCourseCreate, GroupCourseOut, ScheduleCreate, ScheduleOut
from auth import get_async_session, require_role

router = APIRouter(prefix="/admin", tags=["Admin Curriculum Management"])

@router.post("/courses", dependencies=[Depends(require_role("admin"))])
async def create_course(payload: CourseCreate, db: AsyncSession = Depends(get_async_session)):
    # Проверка за дублиране на името
    res_name = await db.execute(select(Course).where(Course.name == payload.name))
    if res_name.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Дисциплина с това име вече съществува.")
    

    new_course = Course(name=payload.name)
    db.add(new_course)
    await db.commit()
    return {"detail": f"Дисциплината '{payload.name}' е създадена успешно!"}


@router.post("/group-courses", dependencies=[Depends(require_role("admin"))])
async def link_group_course(payload: GroupCourseCreate, db: AsyncSession = Depends(get_async_session)):
    # Валидация дали съществуват групата и курса
    group = await db.get(Group, payload.group_id)
    if not group:
        raise HTTPException(status_code=44, detail="Групата не е намерена.")
        
    course = await db.get(Course, payload.course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Дисциплината не е намерена.")

    # Проверка за преподавател (ако е подаден)
    if payload.teacher_id:
        teacher = await db.get(Teacher, payload.teacher_id)
        if not teacher:
            raise HTTPException(status_code=404, detail="Преподавателят не е намерен.")

    # Проверка за композитния уникален ключ (group_id, course_id, type)
    stmt = select(GroupCourse).where(
        and_(
            GroupCourse.group_id == payload.group_id,
            GroupCourse.course_id == payload.course_id,
            GroupCourse.type == payload.type
        )
    )
    res_exist = await db.execute(stmt)
    if res_exist.scalar_one_or_none():
        raise HTTPException(
            status_code=400, 
            detail=f"Вече има създадена връзка за тази група с този предмет за тип занятие: {payload.type}."
        )

    new_link = GroupCourse(
        group_id=payload.group_id,
        course_id=payload.course_id,
        teacher_id=payload.teacher_id,
        type=payload.type,
        semester=payload.semester
    )
    db.add(new_link)
    await db.commit()
    return {"detail": "Предметът е успешно зачислен към учебния план на групата."}



@router.post("/schedules", dependencies=[Depends(require_role("admin"))])
async def create_schedule_slot(payload: ScheduleCreate, db: AsyncSession = Depends(get_async_session)):
    # Валидация: съществува ли изобщо такъв GroupCourse запис
    gc = await db.get(GroupCourse, payload.group_course_id)
    if not gc:
        raise HTTPException(status_code=404, detail="Липсва съответната връзка в учебния план (GroupCourse ID).")

    # Валидация на времевия ред (start_time < end_time)
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="Часът на започване трябва да е преди часа на завършване.")

    # Проверка за композитния уникален ключ (uq_schedule_slot)
    stmt = select(Schedule).where(
        and_(
            Schedule.group_course_id == payload.group_course_id,
            Schedule.day_of_week == payload.day_of_week,
            Schedule.start_time == payload.start_time,
            Schedule.week_parity == payload.week_parity,
            Schedule.subgroup == payload.subgroup
        )
    )
    res_slot = await db.execute(stmt)
    if res_slot.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Този времеви слот в графика вече е зает за това занятие.")

    new_schedule = Schedule(
        group_course_id=payload.group_course_id,
        room_number=payload.room_number,
        day_of_week=payload.day_of_week,
        start_time=payload.start_time,
        end_time=payload.end_time,
        week_parity=payload.week_parity,
        start_date=payload.start_date,
        end_date=payload.end_date,
        subgroup=payload.subgroup
    )
    db.add(new_schedule)
    
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Грешка при база данни: {str(e)}")
        
    return {"detail": "Новото занятие е въведено успешно в графика на залата."}

from schemas import CourseUpdate, GroupCourseUpdate, ScheduleUpdate
# Увери се, че имаш: from sqlalchemy import select, and_

@router.patch("/courses/{course_id}", dependencies=[Depends(require_role("admin"))])
async def update_course(course_id: int, payload: CourseUpdate, db: AsyncSession = Depends(get_async_session)):
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Предметът не е намерен.")

    if payload.name and payload.name != course.name:
        res = await db.execute(select(Course).where(Course.name == payload.name))
        if res.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Вече има предмет с това име.")
        course.name = payload.name

    await db.commit()
    return {"detail": "Предметът е обновен успешно."}

@router.patch("/group-courses/{gc_id}", dependencies=[Depends(require_role("admin"))])
async def update_group_course(gc_id: int, payload: GroupCourseUpdate, db: AsyncSession = Depends(get_async_session)):
    gc = await db.get(GroupCourse, gc_id)
    if not gc:
        raise HTTPException(status_code=404, detail="Връзката в учебния план не е намерена.")

    if payload.teacher_id is not None:
        if payload.teacher_id != 0: 
            teacher = await db.get(Teacher, payload.teacher_id)
            if not teacher:
                raise HTTPException(status_code=404, detail="Новият преподавател не съществува.")
            gc.teacher_id = payload.teacher_id
        else:
            gc.teacher_id = None

    if payload.type and payload.type != gc.type:
        stmt = select(GroupCourse).where(and_(
            GroupCourse.group_id == gc.group_id,
            GroupCourse.course_id == gc.course_id,
            GroupCourse.type == payload.type,
            GroupCourse.id != gc.id  
        ))
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Вече има създадено занятие тип '{payload.type}' за този предмет и група.")
        gc.type = payload.type

    if payload.semester is not None:
        gc.semester = payload.semester

    await db.commit()
    return {"detail": "Зачисляването е обновено."}

@router.patch("/schedules/{schedule_id}", dependencies=[Depends(require_role("admin"))])
async def update_schedule(schedule_id: int, payload: ScheduleUpdate, db: AsyncSession = Depends(get_async_session)):
    sched = await db.get(Schedule, schedule_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Записът в графика не е намерен.")

    new_day = payload.day_of_week if payload.day_of_week is not None else sched.day_of_week
    new_start = payload.start_time if payload.start_time is not None else sched.start_time
    new_end = payload.end_time if payload.end_time is not None else sched.end_time
    new_parity = payload.week_parity if payload.week_parity is not None else sched.week_parity
    
    if payload.subgroup is not None:
        new_subgroup = payload.subgroup if payload.subgroup != "" else None
    else:
        new_subgroup = sched.subgroup

    if new_start >= new_end:
        raise HTTPException(status_code=400, detail="Началният час трябва да е преди крайния.")

    if any([payload.day_of_week is not None, payload.start_time is not None, 
            payload.week_parity is not None, payload.subgroup is not None]):
        
        stmt = select(Schedule).where(and_(
            Schedule.group_course_id == sched.group_course_id,
            Schedule.day_of_week == new_day,
            Schedule.start_time == new_start,
            Schedule.week_parity == new_parity,
            Schedule.subgroup == new_subgroup,
            Schedule.id != sched.id 
        ))
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Този времеви слот в графика вече е зает за това занятие.")

    if payload.room_number: sched.room_number = payload.room_number
    sched.day_of_week = new_day
    sched.start_time = new_start
    sched.end_time = new_end
    sched.week_parity = new_parity
    sched.subgroup = new_subgroup

    if payload.start_date: sched.start_date = payload.start_date
    if payload.end_date: sched.end_date = payload.end_date

    if sched.start_date > sched.end_date:
        raise HTTPException(status_code=400, detail="Началната дата не може да е след крайната.")

    await db.commit()
    return {"detail": "Графикът е обновен успешно."}

@router.get("/courses", response_model=List[CourseOut], dependencies=[Depends(require_role("admin"))])
async def get_courses(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(select(Course))
    return res.scalars().all()

@router.get("/group-courses", response_model=List[GroupCourseOut], dependencies=[Depends(require_role("admin"))])
async def get_group_courses(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(select(GroupCourse))
    return res.scalars().all()

@router.get("/schedules", response_model=List[ScheduleOut], dependencies=[Depends(require_role("admin"))])
async def get_schedules(db: AsyncSession = Depends(get_async_session)):
    res = await db.execute(select(Schedule))
    return res.scalars().all()