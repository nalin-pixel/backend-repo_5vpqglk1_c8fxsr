import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import (
    User, Municipality, Department, Employee, AbsencePeriod,
    Schedule, DailyAssignment, PreferenceInterpretation
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Helpers --------------------
class OID:
    @staticmethod
    def to_str(doc):
        if isinstance(doc, dict) and doc.get("_id"):
            doc["id"] = str(doc.pop("_id"))
        return doc

NORWAY_PUBLIC_HOLIDAYS = {
    # Month-Day pairs for visual marking (not exhaustive)
    (1, 1), (5, 1), (5, 17), (12, 25), (12, 26)
}

SHIFT_TYPES = ["D", "E", "N", "OFF"]

# -------------------- Auth (Simple Demo) --------------------
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    role: str
    username: str

@app.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    user = db.user.find_one({"username": req.username, "is_active": True})
    if not user or user.get("password_hash") != req.password:
        # NOTE: For demo only – compare raw for simplicity
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = f"demo-{user['username']}-{int(datetime.utcnow().timestamp())}"
    db.user.update_one({"_id": user["_id"]}, {"$set": {"session_token": token}})
    return LoginResponse(token=token, role=user["role"], username=user["username"])

# -------------------- Org management --------------------
class CreateMunicipality(BaseModel):
    name: str
    description: Optional[str] = None

@app.post("/api/municipalities")
def create_municipality(body: CreateMunicipality):
    _id = create_document("municipality", Municipality(**body.model_dump()))
    return {"id": _id}

class CreateDepartment(BaseModel):
    municipality_id: str
    name: str

@app.post("/api/departments")
def create_department(body: CreateDepartment):
    _id = create_document("department", Department(**body.model_dump()))
    return {"id": _id}

# -------------------- Employee management --------------------
class CreateEmployee(BaseModel):
    department_id: str
    name: str
    contract_percentage: int
    preferences_text: Optional[str] = None

@app.post("/api/employees")
def create_employee(body: CreateEmployee):
    _id = create_document("employee", Employee(**body.model_dump()))
    return {"id": _id}

@app.get("/api/employees/{department_id}")
def list_employees(department_id: str):
    docs = list(db.employee.find({"department_id": department_id}))
    return [OID.to_str(d) for d in docs]

# -------------------- AI Preference interpretation (mock) --------------------
class InterpretRequest(BaseModel):
    text: str

@app.post("/api/ai/interpret", response_model=PreferenceInterpretation)
def interpret_preferences(req: InterpretRequest):
    text = req.text.lower()
    hard = {}
    soft = {}
    if "never night" in text or "avoid night" in text or "ikke natt" in text:
        hard["no_night"] = True
    if "prefer day" in text or "day shifts" in text or "dagvakt" in text:
        soft["prefer_day"] = 1.0
    if "prefer evening" in text or "kveld" in text:
        soft["prefer_evening"] = 1.0
    if "cannot work after 16" in text or "ikke etter 16" in text:
        hard["no_after_16_friday"] = True
    return PreferenceInterpretation(hard_rules=hard, soft_preferences=soft)

# -------------------- Shift generation --------------------
class GenerateRequest(BaseModel):
    department_id: str
    year: int
    month: int

@app.post("/api/schedule/generate")
def generate_schedule(body: GenerateRequest):
    # Load employees
    employees = list(db.employee.find({"department_id": body.department_id}))
    if not employees:
        raise HTTPException(400, "No employees in department")

    # Build dates for month
    start = date(body.year, body.month, 1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    days = (next_month - start).days

    assignments: List[Dict] = []

    # Simple fair rotation with basic constraints
    for day_offset in range(days):
        d = start + timedelta(days=day_offset)
        weekday = d.weekday()  # 0 Mon ... 6 Sun
        for idx, emp in enumerate(employees):
            # Basic rule: off every 4th day for each employee
            if (day_offset + idx) % 7 == 6:
                shift = "OFF"
            else:
                # Respect simple hard rule
                prefers_no_night = emp.get("hard_rules", {}).get("no_night")
                # Select shift based on weekday and simple rotation
                rotation = ["D", "E", "N"]
                base = rotation[(day_offset + idx) % 3]
                shift = "D" if prefers_no_night and base == "N" else base

                # Friday special rule
                if emp.get("hard_rules", {}).get("no_after_16_friday") and weekday == 4 and shift in ("E", "N"):
                    shift = "D"

            assignments.append({
                "date": d.isoformat(),
                "employee_id": str(emp["_id"]),
                "shift": shift
            })

    schedule_doc = {
        "department_id": body.department_id,
        "year": body.year,
        "month": body.month,
        "assignments": assignments,
        "created_at": datetime.utcnow(),
    }
    result = db.schedule.insert_one(schedule_doc)
    return {"id": str(result.inserted_id), "assignments": assignments}

@app.get("/api/schedule/{department_id}/{year}/{month}")
def get_schedule(department_id: str, year: int, month: int):
    doc = db.schedule.find_one({"department_id": department_id, "year": year, "month": month})
    if not doc:
        raise HTTPException(404, "Schedule not found")
    doc["id"] = str(doc.pop("_id"))
    return doc

# -------------------- Utility --------------------
@app.get("/")
def read_root():
    return {"message": "Turnus Planner Backend Running"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
