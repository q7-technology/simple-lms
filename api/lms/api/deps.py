from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session as Db

from lms.db import get_sessionmaker


def get_db():
    with get_sessionmaker()() as session:
        yield session


DB = Annotated[Db, Depends(get_db)]
