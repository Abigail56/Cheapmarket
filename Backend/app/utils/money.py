from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import PlainSerializer

TWO = Decimal("0.01")


def q2(value: Decimal | float | str) -> Decimal:
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


# Decimal in, plain JSON number out (easier for the frontend than strings)
Money = Annotated[
    Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")
]
