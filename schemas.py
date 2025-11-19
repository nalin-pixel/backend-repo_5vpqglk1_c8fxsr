"""
Database Schemas for Turnus Planner

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
"""
from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field
from datetime import date

# -------------------- Auth & Org --------------------
class User(BaseModel):
    username: str = Field(..., description="Unique login username")
    password_hash: str = Field(..., description="SHA256 hash of password")
    role: Literal["municipal_admin", "department_leader"] = Field(...)
    municipality_ids: List[str] = Field(default_factory=list)
    department_ids: List[str] = Field(default_factory=list)
    session_token: Optional[str] = None
    is_active: bool = True

class Municipality(BaseModel):
    name: str
    description: Optional[str] = None

class Department(BaseModel):
    municipality_id: str
    name: str
    leader_user_id: Optional[str] = None
    settings: Dict = Field(default_factory=dict)

# -------------------- Employees & Preferences --------------------
class AbsencePeriod(BaseModel):
    start: date
    end: date
    reason: Optional[str] = None

class Employee(BaseModel):
    department_id: str
    name: str
    contract_percentage: int = Field(ge=1, le=200)
    preferences_text: Optional[str] = None
    hard_rules: Dict = Field(default_factory=dict)
    soft_preferences: Dict = Field(default_factory=dict)
    absences: List[AbsencePeriod] = Field(default_factory=list)

# -------------------- Schedules --------------------
ShiftType = Literal["D", "E", "N", "OFF"]  # Day, Evening, Night, Off

class DailyAssignment(BaseModel):
    date: date
    employee_id: str
    shift: ShiftType

class Schedule(BaseModel):
    department_id: str
    month: int
    year: int
    assignments: List[DailyAssignment] = Field(default_factory=list)
    notes: Optional[str] = None

# -------------------- AI Interpretation --------------------
class PreferenceInterpretation(BaseModel):
    hard_rules: Dict = Field(default_factory=dict)
    soft_preferences: Dict = Field(default_factory=dict)
