from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from database import SessionLocal, SPAC, Alert, Base, engine

Base.metadata.create_all(bind=engine)

app = FastAPI(title="SPAC Research API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SPACResponse(BaseModel):
    id: int
    ticker: str
    company: str
    price: float
    premium: float
    deal_status: str
    target: Optional[str] = None
    expected_close: Optional[str] = None
    days_to_deadline: Optional[int] = None
    market_cap: float
    risk_level: str
    sector: str
    banker: str
    last_updated: datetime
    
    class Config:
        from_attributes = True

class AlertCreate(BaseModel):
    user_email: str
    alert_type: str
    ticker: Optional[str] = None
    condition: str

@app.get("/")
def read_root():
    return {"message": "SPAC Research API - Running!", "version": "1.0.0"}

@app.get("/spacs", response_model=List[SPACResponse])
def get_spacs(
    skip: int = 0,
    limit: int = 200,
    deal_status: Optional[str] = None,
    min_premium: Optional[float] = None,
    max_premium: Optional[float] = None,
    risk_level: Optional[str] = None,
    banker: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(SPAC)
    
    if deal_status:
        query = query.filter(SPAC.deal_status == deal_status)
    if min_premium is not None:
        query = query.filter(SPAC.premium >= min_premium)
    if max_premium is not None:
        query = query.filter(SPAC.premium <= max_premium)
    if risk_level:
        query = query.filter(SPAC.risk_level == risk_level)
    if banker:
        query = query.filter(SPAC.banker == banker)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (SPAC.ticker.ilike(search_term)) |
            (SPAC.company.ilike(search_term)) |
            (SPAC.target.ilike(search_term))
        )
    
    return query.offset(skip).limit(limit).all()

@app.get("/spacs/{ticker}", response_model=SPACResponse)
def get_spac(ticker: str, db: Session = Depends(get_db)):
    spac = db.query(SPAC).filter(SPAC.ticker == ticker).first()
    if not spac:
        raise HTTPException(status_code=404, detail="SPAC not found")
    return spac

@app.get("/analytics/summary")
def get_analytics_summary(db: Session = Depends(get_db)):
    total_spacs = db.query(SPAC).count()
    announced_deals = db.query(SPAC).filter(SPAC.deal_status == "ANNOUNCED").count()
    near_nav = db.query(SPAC).filter(SPAC.premium.between(-5, 5)).count()
    urgent = db.query(SPAC).filter(
        SPAC.days_to_deadline < 90,
        SPAC.days_to_deadline > 0
    ).count()
    
    total_market_cap = sum([s.market_cap for s in db.query(SPAC).all() if s.market_cap])
    
    from collections import Counter
    bankers = [s.banker for s in db.query(SPAC).all()]
    banker_distribution = Counter(bankers)
    
    return {
        "total_spacs": total_spacs,
        "announced_deals": announced_deals,
        "near_nav_count": near_nav,
        "urgent_count": urgent,
        "total_market_cap_millions": round(total_market_cap, 2),
        "top_bankers": dict(banker_distribution.most_common(10))
    }

@app.post("/alerts")
def create_alert(alert: AlertCreate, db: Session = Depends(get_db)):
    db_alert = Alert(**alert.dict())
    db.add(db_alert)
    db.commit()
    db.refresh(db_alert)
    return {"status": "success", "alert_id": db_alert.id}

@app.get("/alerts/{email}")
def get_user_alerts(email: str, db: Session = Depends(get_db)):
    alerts = db.query(Alert).filter(Alert.user_email == email, Alert.active == True).all()
    return alerts
