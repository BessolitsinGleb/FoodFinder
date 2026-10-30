from pydantic import BaseModel, EmailStr, Field, field_validator
from app.domain.geo import normalize_city
from app.schemas.common import Schema
from app.schemas.user import normalize_email, validate_region

class RegisterRequest(Schema):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    city: str = Field(min_length=1, max_length=100, examples=["Казань"])
    region: str = Field(min_length=1, max_length=100, examples=["Республика Татарстан"])

    _email_lower = field_validator("email")(normalize_email)
    _city = field_validator("city")(normalize_city)
    _region = field_validator("region")(validate_region)

class VerifyEmailRequest(Schema):
    email: EmailStr
    # Ровно 6 цифр — всё остальное отсекаем ещё до проверки (422)
    code: str = Field(pattern=r"^\d{6}$")

    _email_lower = field_validator("email")(normalize_email)

class ResendCodeRequest(Schema):
    email: EmailStr

    _email_lower = field_validator("email")(normalize_email)

class MessageResponse(BaseModel):
    message: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
