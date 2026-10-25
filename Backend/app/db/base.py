"""Import every model here so Alembic's autogenerate can see them."""
from sqlmodel import SQLModel

from app.models import *

metadata = SQLModel.metadata
