"""Strict structured-output contracts shared by web model calls."""

from pydantic import BaseModel, Field


class ListingContract(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    bullets: list[str] = Field(min_length=5, max_length=5)
    description: str = Field(min_length=20)
    keywords: list[str] = Field(min_length=3, max_length=20)


class OpportunityContract(BaseModel):
    name: str = Field(min_length=3)
    cat: str
    score: float = Field(ge=0, le=10)
    margin: str
    demand: str
    comp: str
    reason: str


class OpportunityListContract(BaseModel):
    items: list[OpportunityContract]
