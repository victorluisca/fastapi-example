from fastapi import FastAPI, HTTPException, Depends, Query, Request
from sqlmodel import SQLModel, Session, create_engine, select, Field, func
from contextlib import asynccontextmanager
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import List, Annotated, Generic, TypeVar, Optional
from math import ceil


class Campaign(SQLModel, table=True):
    campaign_id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    due_date: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )


class CampaignCreate(SQLModel):
    name: str
    due_date: datetime | None = None


sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        if not session.exec(select(Campaign)).first():
            session.add_all(
                [
                    Campaign(name="Summer Launch", due_date=datetime.now(timezone.utc)),
                    Campaign(name="Black Friday", due_date=datetime.now(timezone.utc)),
                ]
            )
            session.commit()
    yield


app = FastAPI(root_path="/api/v1", lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello, World!"}


T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    data: T


class PaginatedResponse(BaseModel, Generic[T]):
    data: T
    next: Optional[str]
    prev: Optional[str]
    offset: int
    limit: int
    total_items: int
    total_pages: int


@app.get("/campaigns", response_model=PaginatedResponse[List[Campaign]])
async def read_campaigns(
    session: SessionDep,
    request: Request,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1),
):
    data = session.exec(
        select(Campaign).order_by(Campaign.campaign_id).offset(offset).limit(limit)  # type: ignore
    ).all()

    total_items = session.exec(select(func.count()).select_from(Campaign)).one()

    total_pages = max(1, ceil(total_items / limit))

    base_url = str(request.base_url)

    next_url = f"{base_url}campaigns?offset={offset + limit}&limit={limit}"

    if offset > 0:
        prev_url = f"{base_url}campaigns?offset={max(0, offset - limit)}&limit={limit}"
    else:
        prev_url = None

    return PaginatedResponse(
        data=data,
        next=next_url,
        prev=prev_url,
        offset=offset,
        limit=limit,
        total_items=total_items,
        total_pages=total_pages,
    )


@app.get("/campaigns/{id}", response_model=Response[Campaign])
async def read_campaign(
    session: SessionDep,
    id: int,
):
    data = session.get(Campaign, id)
    if not data:
        raise HTTPException(status_code=404)

    return {"data": data}


@app.post("/campaigns", response_model=Response[Campaign], status_code=201)
async def create_campaign(session: SessionDep, campaign: CampaignCreate):
    db_campaign = Campaign.model_validate(campaign)

    session.add(db_campaign)
    session.commit()
    session.refresh(db_campaign)

    return {"data": db_campaign}


@app.put("/campaigns/{id}", response_model=Response[Campaign])
async def update_campaign(session: SessionDep, id: int, campaign: CampaignCreate):
    data = session.get(Campaign, id)
    if not data:
        raise HTTPException(status_code=404)

    data.name = campaign.name
    data.due_date = campaign.due_date

    session.add(data)
    session.commit()
    session.refresh(data)

    return {"data": data}


@app.delete("/campaigns/{id}", status_code=204)
async def delete_campaign(session: SessionDep, id: int):
    data = session.get(Campaign, id)
    if not data:
        raise HTTPException(status_code=404)

    session.delete(data)
    session.commit()
