from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

SAT = int

@dataclass
class Payment:
    src: "NodeBase"
    dst: "NodeBase"
    amount: SAT
    created: float
    method: str          
    completed: Optional[float] = None
    fee: SAT = 0
    latency: float = 0.0

class NodeBase:
    sent: list[Payment]
    received: list[Payment]
    balance: SAT = 0
