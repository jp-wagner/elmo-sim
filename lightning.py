from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Dict, List, Optional

import simpy
import itertools

from common import SAT, Payment, NodeBase
from layer1 import LEDGER_DELAY

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CLTV_DELTA = 40              # blocks
OFFCHAIN_HOP_DELAY = 0.2             # seconds per hop (user-perceived)
RISK_PPM = 1                         # 1 ppm per block ≃ LND default

# ---------------------------------------------------------------------------
# Fee
# ---------------------------------------------------------------------------
@dataclass
class FeePolicy:
    base_fee: SAT = 1          # 1 sat ( = 1 000 msat)
    fee_rate_ppm: int = 1      # 1 ppm

    def fee(self, amount_sat: SAT) -> SAT:
        return self.base_fee + (amount_sat * self.fee_rate_ppm) // 1_000_000

# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------
class Channel:
    def __init__(self,
                 env: simpy.Environment,
                 n1: "Node",
                 n2: "Node",
                 capacity: SAT,
                 *,
                 cltv_delta: int = DEFAULT_CLTV_DELTA,
                 policy: Optional[FeePolicy] = None):
        self.env = env
        self.n1, self.n2 = n1, n2
        self.capacity = capacity
        self.cltv_delta = cltv_delta
        self.policy = policy or FeePolicy()
        half = capacity // 2
        self.balance: Dict["Node", SAT] = {n1: half, n2: capacity - half}

    def other(self, node: "Node") -> "Node":
        return self.n2 if node is self.n1 else self.n1

    def move(self, src: "Node", amount: SAT):
        if self.balance[src] < amount:
            raise ValueError("insufficient balance")
        dst = self.other(src)
        self.balance[src] -= amount
        self.balance[dst] += amount

# ---------------------------------------------------------------------------
# Node 
# ---------------------------------------------------------------------------
class Node(NodeBase):
    def __init__(self, env: simpy.Environment, name: str):
        self.env = env
        self.name = name
        self.channels: Dict["Node", Channel] = {}
        self.sent: List[Payment] = []
        self.received: List[Payment] = []


    # -- topology helpers ----------------------------------------------------
    def connect(self, other: "Node", capacity: SAT):
        ch = Channel(self.env, self, other, capacity)
        self.channels[other] = ch
        other.channels[self] = ch
        return ch

    # -- path-finding: fee+risk Dijkstra ------------------------------------
    def _dijkstra(self, dst: "Node", amount_sat: SAT) -> Optional[List["Node"]]:
        counter = itertools.count()
        dist: Dict["Node", float] = {self: 0.0}
        prev: Dict["Node", "Node"] = {}
        pq: list[tuple[float, int, "Node"]] = [(0.0, next(counter), self)]

        while pq:
            cost_u, _, u = heapq.heappop(pq)
            if u is dst:
                # reconstruct
                path = [dst]
                while path[-1] is not self:
                    path.append(prev[path[-1]])
                return list(reversed(path))
            if cost_u > dist[u]:
                continue
            for v, ch in u.channels.items():
                fee = ch.policy.fee(amount_sat)
                risk = (RISK_PPM * amount_sat * ch.cltv_delta) / 1_000_000
                w = fee + risk
                alt = cost_u + w
                if v not in dist or alt < dist[v]:
                    dist[v] = alt
                    prev[v] = u
                    heapq.heappush(pq, (alt, next(counter), v))  # second field = tie-breaker
        return None

    # -- payment -------------------------------------------------------------
    def send_payment_PC(self, dst: "Node", amount_sat: SAT) -> Payment:
        env = self.env
        path = self._dijkstra(dst, amount_sat)
        if not path or len(path) < 2:
            raise ValueError("no route")

        chans = [path[i].channels[path[i + 1]] for i in range(len(path) - 1)]

        # backward fee escalation 
        hop_send:  list[SAT] = [0] * len(chans)   # HTLC size on this hop
        hop_fee:   list[SAT] = [0] * len(chans)   # fee earned by that hop

        to_forward = amount_sat                   # starts with receiver amount
        for i in reversed(range(len(chans))):
            fee = 0 if i == len(chans) - 1 else chans[i].policy.fee(to_forward)
            hop_fee[i]   = fee
            hop_send[i]  = to_forward + fee       # what the payer must lock
            to_forward  += fee                    # grows as we move backwards

        # liquidity check  
        for i, ch in enumerate(chans):
            if ch.balance[path[i]] < hop_send[i]:
                raise ValueError(f"liquidity shortfall at hop {i}")

        # execute moves 
        for i, ch in enumerate(chans):
            ch.move(path[i], hop_send[i])

        # bookkeeping 
        p = Payment(self, dst, amount_sat, env.now, method="lightning")
        p.fee     = sum(hop_fee)
        p.latency = len(chans) * OFFCHAIN_HOP_DELAY
        p.completed = None                       

        self.sent.append(p)
        dst.received.append(p)

        # schedule completion
        def _settle():
            yield env.timeout(p.latency)
            p.completed = env.now
        env.process(_settle())

        return p

    def __repr__(self):
        return f"<Node {self.name}>"
