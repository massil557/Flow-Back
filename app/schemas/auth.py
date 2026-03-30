from pydantic import BaseModel

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class UserPublic(BaseModel):
    id: int
    username: str
    role: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str