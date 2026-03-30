from pydantic import BaseModel
from typing import Optional

class UserCreate_Admin(BaseModel):
    username: str
    email: str
    role: str

class UserUpdate_Admin(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    username: Optional[str] = None

class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str]
    role: str