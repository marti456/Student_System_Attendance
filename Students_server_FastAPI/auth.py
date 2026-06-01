import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select
from typing import List, Optional

from models import AsyncSessionLocal, Student, Teacher, User, engine_url, Group
from schemas import (
    GroupOut, StudentOut, StudentUpdate, TeacherOut, TeacherUpdate,
    Token, TokenData, UserCreate, UserOut,
    StudentRegisterIn, TeacherRegisterIn, AdminRegisterIn,
    ProvisionKeyOut,
)

SECRET_KEY = "CHANGE_ME_TO_A_RANDOM_SECRET"
ALGORITHM  = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
router = APIRouter()


async def get_async_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def authenticate_user(db: AsyncSession, username: str, password: str) -> Optional[User]:
    res  = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()
    if not user or not user.verify_password(password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire    = datetime.now() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_session),
):
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Грешно потребителско име или парола.")
    token = create_access_token({"sub": user.username, "role": user.role, "user_id": user.id})
    return {"access_token": token, "token_type": "bearer"}


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db:    AsyncSession = Depends(get_async_session),
) -> User:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалиден токен.")
    try:
        payload  = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise exc
    except JWTError:
        raise exc
    res  = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()
    if user is None:
        raise exc
    return user


def require_role(role: str):
    async def checker(current_user: User = Depends(get_current_user)):
        if current_user.role != role and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Недостатъчни права.")
        return current_user
    return checker


def require_any_role(roles: list):
    async def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Недостатъчни права.")
        return current_user
    return checker


# ──────────────────────────────────────────────
# НОВ ENDPOINT: Провизиониране на HMAC ключ
# ──────────────────────────────────────────────

@router.post("/provision-key", response_model=ProvisionKeyOut)
async def provision_key(
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    """
    Извиква се от Android приложението веднага след успешен логин.
    Генерира (при нужда) уникален HMAC ключ за студента и го връща.
    Ключът се пази в Android Keystore — никога не напуска телефона след това.
    """
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Само студенти могат да получат NFC ключ.")

    if not current_user.linked_student_id:
        raise HTTPException(status_code=400, detail="Акаунтът не е свързан с профил на студент.")

    student = await db.get(Student, current_user.linked_student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен.")

    if not student.hmac_key:
        # Генерираме 32 криптографски случайни байта (256-bit ключ)
        student.hmac_key = secrets.token_hex(32)
        student.atc_counter = 0
        await db.commit()
        await db.refresh(student)

    return ProvisionKeyOut(
        hmac_key       = student.hmac_key,
        faculty_number = student.faculty_number,
        atc            = student.atc_counter,
    )


@router.post("/provision-key/reset", dependencies=[Depends(require_role("admin"))])
async def reset_provision_key(
    student_id: int,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Само за администратор: нулира ключа на студент (напр. при смяна на телефон).
    При следващ /provision-key от студента ще се генерира нов ключ.
    """
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен.")

    student.hmac_key    = None
    student.atc_counter = 0
    await db.commit()
    return {"detail": f"HMAC ключът на студент {student.faculty_number} е нулиран."}


# ──────────────────────────────────────────────
# РЕГИСТРАЦИИ
# ──────────────────────────────────────────────

@router.post("/register/student", dependencies=[Depends(require_role("admin"))])
async def register_student(payload: StudentRegisterIn, db: AsyncSession = Depends(get_async_session)):
    if (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Потребителското име вече е заето.")
    if (await db.execute(select(Student).where(Student.faculty_number == payload.faculty_number))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Студент с този факултетен номер вече съществува.")

    try:
        group_res = await db.execute(
            select(Group).where(and_(
                Group.name  == payload.group_name,
                Group.year  == payload.group_year,
                Group.major == payload.group_major,
            ))
        )
        group = group_res.scalar_one_or_none()
        if not group:
            group = Group(name=payload.group_name, year=payload.group_year, major=payload.group_major)
            db.add(group)
            await db.flush()

        new_student = Student(
            faculty_number = payload.faculty_number,
            rfid_uid       = payload.rfid_uid,   # може да е None
            name           = payload.name,
            group_id       = group.id,
        )
        db.add(new_student)
        await db.flush()

        new_user = User(
            username          = payload.username,
            password_hash     = User.hash_password(payload.password),
            role              = "student",
            linked_student_id = new_student.student_id,
        )
        db.add(new_user)
        await db.commit()
        return {"detail": f"Студентът {payload.name} е регистриран успешно!"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Системна грешка: {str(e)}")


@router.post("/register/teacher", dependencies=[Depends(require_role("admin"))])
async def register_teacher(payload: TeacherRegisterIn, db: AsyncSession = Depends(get_async_session)):
    if (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Потребителското име вече е заето.")
    try:
        new_teacher = Teacher(name=payload.name, department=payload.department, title=payload.title)
        db.add(new_teacher)
        await db.flush()
        new_user = User(
            username          = payload.username,
            password_hash     = User.hash_password(payload.password),
            role              = "teacher",
            linked_teacher_id = new_teacher.id,
        )
        db.add(new_user)
        await db.commit()
        return {"detail": f"Преподавателят {payload.name} е регистриран успешно!"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Системна грешка: {str(e)}")


@router.post("/register/admin", dependencies=[Depends(require_role("admin"))])
async def register_admin(payload: AdminRegisterIn, db: AsyncSession = Depends(get_async_session)):
    if (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Потребителското име вече е заето.")
    try:
        db.add(User(username=payload.username, password_hash=User.hash_password(payload.password), role="admin"))
        await db.commit()
        return {"detail": f"Администраторът {payload.username} е създаден."}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Системна грешка: {str(e)}")


# ──────────────────────────────────────────────
# UPDATE ENDPOINTS
# ──────────────────────────────────────────────

@router.patch("/students/{student_id}", dependencies=[Depends(require_role("admin"))])
async def update_student(student_id: int, payload: StudentUpdate, db: AsyncSession = Depends(get_async_session)):
    student = await db.get(Student, student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен.")

    if payload.faculty_number and payload.faculty_number != student.faculty_number:
        if (await db.execute(select(Student).where(Student.faculty_number == payload.faculty_number))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Факултетният номер вече съществува.")
        student.faculty_number = payload.faculty_number

    if payload.rfid_uid and payload.rfid_uid != student.rfid_uid:
        if (await db.execute(select(Student).where(Student.rfid_uid == payload.rfid_uid))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Този RFID вече се използва.")
        student.rfid_uid = payload.rfid_uid

    if payload.name:
        student.name = payload.name

    if any([payload.group_name, payload.group_year, payload.group_major]):
        curr = await db.get(Group, student.group_id)
        gn = payload.group_name  or curr.name
        gy = payload.group_year  or curr.year
        gm = (payload.group_major.upper() if payload.group_major else curr.major)
        res = await db.execute(select(Group).where(and_(Group.name == gn, Group.year == gy, Group.major == gm)))
        tg = res.scalar_one_or_none()
        if not tg:
            tg = Group(name=gn, year=gy, major=gm)
            db.add(tg)
            await db.flush()
        student.group_id = tg.id

    await db.commit()
    return {"detail": "Данните на студента са обновени."}


@router.patch("/teachers/{teacher_id}", dependencies=[Depends(require_role("admin"))])
async def update_teacher(teacher_id: int, payload: TeacherUpdate, db: AsyncSession = Depends(get_async_session)):
    teacher = await db.get(Teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="Преподавателят не е намерен.")
    if payload.name:        teacher.name       = payload.name
    if payload.title is not None:  teacher.title  = payload.title
    if payload.department is not None: teacher.department = payload.department
    await db.commit()
    return {"detail": "Данните на преподавателя са обновени."}


# ──────────────────────────────────────────────
# GET ENDPOINTS
# ──────────────────────────────────────────────

@router.get("/groups",   response_model=List[GroupOut],   dependencies=[Depends(require_any_role(["admin", "teacher"]))])
async def get_groups(db: AsyncSession = Depends(get_async_session)):
    return (await db.execute(select(Group))).scalars().all()

@router.get("/students", response_model=List[StudentOut], dependencies=[Depends(require_any_role(["admin", "teacher"]))])
async def get_students(db: AsyncSession = Depends(get_async_session)):
    return (await db.execute(select(Student))).scalars().all()

@router.get("/teachers", response_model=List[TeacherOut], dependencies=[Depends(require_any_role(["admin", "teacher"]))])
async def get_teachers(db: AsyncSession = Depends(get_async_session)):
    return (await db.execute(select(Teacher))).scalars().all()