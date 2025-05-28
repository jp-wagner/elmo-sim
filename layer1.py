from __future__ import annotations

import simpy
from common import SAT, Payment, NodeBase

LEDGER_DELAY = 600            # Bitcoin block time (s)
DEFAULT_FEE_RATE = 25         # sat/vbyte
DEFAULT_TX_SIZE = 250         # vbytes for a simple P2WPKH tx
DEFAULT_CONF_TARGET = 6       # blocks to finality

class BitcoinMainchain:
    def __init__(self,
                 fee_rate_sat_per_vb: int = DEFAULT_FEE_RATE,
                 tx_size_vb: int = DEFAULT_TX_SIZE,
                 conf_target_blocks: int = DEFAULT_CONF_TARGET,
                 block_time: int = LEDGER_DELAY):
        self.fee_rate = fee_rate_sat_per_vb
        self.tx_size = tx_size_vb
        self.conf_target = conf_target_blocks
        self.block_time = block_time

    def _now(self, env: simpy.Environment) -> float:
        return env.now

    def send_payment_l1(self,
                 env: simpy.Environment,
                 src: "NodeBase",
                 dst: "NodeBase",
                 amount: SAT) -> Payment:

        fee     = self.tx_size * self.fee_rate
        latency = self.conf_target * self.block_time

        if src.balance < amount + fee:
            raise ValueError("insufficient funds")

        p = Payment(src, dst, amount, env.now, method="onchain")
        p.fee     = fee
        p.latency = latency
        p.completed = None                       

        src.balance -= amount + fee
        dst.balance += amount
        src.sent.append(p)
        dst.received.append(p)

        # confirmation process
        def _confirm():
            yield env.timeout(latency)
            p.completed = env.now
        env.process(_confirm())

        return p
