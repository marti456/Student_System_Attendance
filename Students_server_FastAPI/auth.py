from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select
from models import AsyncSessionLocal, Student, Teacher, User, engine_url, Group
from schemas import Token, TokenData
from typing import Optional, Callable
from schemas import Token, TokenData, UserCreate, UserOut, StudentRegisterIn, TeacherRegisterIn, AdminRegisterIn

# secret for signing tokens (change in production)
SECRET_KEY = "CHANGE_ME_TO_A_RANDOM_SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

router = APIRouter()

async def get_async_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

async def authenticate_user(db: AsyncSession, username: str, password: str) -> Optional[User]:
    res = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()
    if not user:
        return None
    if not user.verify_password(password):
        return None
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_async_session)):
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token_data = {"sub": user.username, "role": user.role, "user_id": user.id}
    access_token = create_access_token(token_data)
    return {"access_token": access_token, "token_type": "bearer"}

# Dependency: get current user
async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_async_session)) -> User:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    res = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user

def require_role(role: str):
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role != role and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker

def require_any_role(roles: list):
    async def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in roles and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return checker

# @router.post("/users", response_model=UserOut, dependencies=[Depends(require_role("admin"))])
# async def create_new_user(
#     user_data: UserCreate, 
#     db: AsyncSession = Depends(get_async_session)
# ):
#     res = await db.execute(select(User).where(User.username == user_data.username))
#     if res.scalar_one_or_none():
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST, 
#             detail="Потребителското име вече е заето"
#         )

#     hashed_password = User.hash_password(user_data.password)

#     new_user = User(
#         username=user_data.username,
#         password_hash=hashed_password,
#         role=user_data.role,
#         linked_student_id=user_data.linked_student_id
#     )

#     db.add(new_user)
#     try:
#         await db.commit()
#         await db.refresh(new_user)
#     except Exception:
#         await db.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
#             detail="Грешка при запис в базата данни"
#         )

#     return new_user

@router.post("/register/student", dependencies=[Depends(require_role("admin"))])
async def register_student(payload: StudentRegisterIn, db: AsyncSession = Depends(get_async_session)):
    # 1. Проверки за дублиране на потребител или факултетен номер
    user_exists = await db.execute(select(User).where(User.username == payload.username))
    if user_exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Потребителското име вече е заето.")
        
    fn_exists = await db.execute(select(Student).where(Student.faculty_number == payload.faculty_number))
    if fn_exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Студент с този факултетен номер вече съществува.")

    try:
        # 2. Търсим групата по новия композитен ключ (Име + Курс + Специалност)
        group_res = await db.execute(
            select(Group).where(
                and_(
                    Group.name == payload.group_name,
                    Group.year == payload.group_year,
                    Group.major == payload.group_major
                )
            )
        )
        group = group_res.scalar_one_or_none()
        
        # АКО ТАЗИ СПЕЦИФИЧНА ГРУПА НЕ СЪЩЕСТВУВА, Я СЪЗДАВАМЕ АВТОМАТИЧНО
        if not group:
            group = Group(
                name=payload.group_name,
                year=payload.group_year,
                major=payload.group_major
            )
            db.add(group)
            await db.flush() # Вземаме генерираното group.id в паметта

        # 3. Създаваме студента с правилното групово ID
        new_student = Student(
            faculty_number=payload.faculty_number,
            rfid_uid=payload.rfid_uid,
            name=payload.name,
            group_id=group.id  
        )
        db.add(new_student)
        await db.flush() 

        # 4. Създаваме потребителския акаунт за вход
        new_user = User(
            username=payload.username,
            password_hash=User.hash_password(payload.password),
            role="student",
            linked_student_id=new_student.student_id
        )
        db.add(new_user)
        
        await db.commit() 
        return {"detail": f"Студентът {payload.name} е регистриран успешно в група {payload.group_name}, {payload.group_year} курс, специалност {payload.group_major}!"}
        
    except Exception as e:
        await db.rollback() 
        raise HTTPException(status_code=500, detail=f"Системна грешка при запис: {str(e)}")

@router.post("/register/teacher", dependencies=[Depends(require_role("admin"))])
async def register_teacher(payload: TeacherRegisterIn, db: AsyncSession = Depends(get_async_session)):
    user_exists = await db.execute(select(User).where(User.username == payload.username))
    if user_exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Потребителското име вече е заето.")

    try:
        # Първо създаваме преподавателя
        new_teacher = Teacher(
            name=payload.name,
            department=payload.department
        )
        db.add(new_teacher)
        await db.flush()

        # Второ създаваме уеб потребителя
        new_user = User(
            username=payload.username,
            password_hash=User.hash_password(payload.password),
            role="teacher",
            linked_teacher_id=new_teacher.id
        )
        db.add(new_user)
        
        await db.commit()
        return {"detail": f"Преподавателят {payload.name} е регистриран успешно!"}
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Системна грешка при запис: {str(e)}")
    
@router.post("/register/admin", dependencies=[Depends(require_role("admin"))])
async def register_admin(payload: AdminRegisterIn, db: AsyncSession = Depends(get_async_session)):
    user_exists = await db.execute(select(User).where(User.username == payload.username))
    if user_exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Потребителското име вече е заето.")

    try:
        new_user = User(
            username=payload.username,
            password_hash=User.hash_password(payload.password),
            role="admin"
        )
        db.add(new_user)
        await db.commit()
        return {"detail": f"Администраторът {payload.username} е създаден успешно!"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Системна грешка при запис: {str(e)}")