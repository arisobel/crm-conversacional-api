from pydantic import BaseModel


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None

