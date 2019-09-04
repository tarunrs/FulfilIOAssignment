from sqlalchemy import Column, String, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()
class Product(Base):
    __tablename__ = 'products'
    sku = Column(String, primary_key=True)
    name = Column(String)
    description = Column(String)
    is_active = Column(Boolean)
