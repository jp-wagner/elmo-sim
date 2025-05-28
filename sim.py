from __future__ import annotations
import random, statistics, simpy
from typing import List
from common   import Payment, SAT
from layer1   import BitcoinMainchain
from lightning import Node
from topo     import generate_LN_topology

# ---------------------------------------------------------------------------
# Workload generator 
# ---------------------------------------------------------------------------
def make_workload(nodes: List[Node],
                  num_payments: int = 10,
                  min_sat: SAT = 1_000,
                  max_sat: SAT = 100_000,
                  rng=random) -> list[tuple[Node, Node, SAT]]:

    txs = []
    for _ in range(num_payments):
        src, dst = rng.sample(nodes, 2)
        amt = rng.randint(min_sat, max_sat)
        txs.append((src, dst, amt))
    return txs

# ---------------------------------------------------------------------------
# Execute workload on Bitcoin L1 
# ---------------------------------------------------------------------------
def run_onchain(nodes: List[Node], txs) -> Metrics:
    env   = simpy.Environment()
    chain = BitcoinMainchain()
    m     = Metrics()

    print_wallets(nodes, "\nInitial on-chain wallet balances:")

    for src, dst, amt in txs:
        m.add(chain.send_payment_l1(env, src, dst, amt))
        env.run(until=env.now + 1)   # advance 1 s between submissions

    print("\n=== On-chain payment log ===")
    print(m.payment_log())
    print_wallets(nodes, "\nFinal on-chain wallet balances:")
    print("\n=== On-chain metrics ===")
    print(m.summary_table())
    return m

# ---------------------------------------------------------------------------
# Execute workload on Lightning 
# ---------------------------------------------------------------------------
def run_lightning(nodes: List[Node], txs) -> Metrics:
    print_channels(nodes, "Initial channel balances:")

    m = Metrics()
    for src, dst, amt in txs:
        try:
            m.add(src.send_payment_PC(dst, amt))
        except ValueError:
            m.add(None)

    print("\n=== Lightning payment log ===")
    print(m.payment_log())
    print_channels(nodes, "\nFinal channel balances:")
    print("\n=== Lightning metrics ===")
    print(m.summary_table())
    return m

# ---------------------------------------------------------------------------
# Metrics  
# ---------------------------------------------------------------------------
class Metrics:
    def __init__(self):
        self.payments: List[Payment] = []
        self.failed = 0

    def add(self, p: Payment | None):
        self.failed += p is None
        if p: self.payments.append(p)

    # ---------- pretty printers --------------------------------------------
    def payment_log(self, max_lines: int = 25) -> str:
        lines = [f"{p.src.name:>4} ── {p.amount:>7,d} sat ─▶ {p.dst.name:<4}"
                 for p in self.payments[:max_lines]]
        if len(self.payments) > max_lines:
            lines.append("  …")
        return "\n".join(lines) if lines else "  (no successful payments)"

    def summary_table(self) -> str:
        moved = sum(p.amount for p in self.payments)
        fee   = sum(p.fee for p in self.payments)
        lat   = [p.latency for p in self.payments]
        rows = [
            ("payments",            f"{len(self.payments):d}"),
            ("failed",              f"{self.failed:d}"),
            ("satoshi moved",       f"{moved:,d}"),
            ("total fee (sat)",     f"{fee:,d}"),
            ("avg fee per ksat",    f"{fee/moved*1000:,.2f}" if moved else "0"),
            ("mean latency (s)",    f"{statistics.mean(lat):.3f}" if lat else "0"),
            ("p95 latency (s)",
             f"{statistics.quantiles(lat, n=20)[18]:.3f}" if len(lat) >= 20
             else (max(lat) if lat else 0)),
        ]
        return "\n".join(f"{k:<18} {v:>12}" for k, v in rows)

# ---------------------------------------------------------------------------
# Helpers to show node & channel balances 
# ---------------------------------------------------------------------------
def print_wallets(nodes: List[Node], header: str):
    print(header)
    for n in nodes:
        print(f"  {n.name}: {n.balance:,} sat")

def print_channels(nodes: List[Node], header: str):
    seen = set()
    lines = []
    for n in nodes:
        for peer, ch in n.channels.items():
            if (n, peer) in seen or (peer, n) in seen: continue
            lines.append(f"  {n.name} ⇄  {peer.name}: "
                         f"{ch.balance[n]:,}/{ch.balance[peer]:,} sat "
                         f"(cap {ch.capacity:,})")
            seen.add((n, peer))
    print(header)
    print("\n".join(lines) if lines else "  (no channels)")


# --------------------------------------------------------------------------
# Demos
# ---------------------------------------------------------------------------
def demo():
    rng = random.Random()                       
    env = simpy.Environment()
    nodes = generate_LN_topology(env, num_nodes=25, m=1, draw_png=True)
    for n in nodes:                               
        n.balance = 2_000_000

    # prepare identical workload
    workload = make_workload(nodes, num_payments=10, rng=rng)

    print("\n========== BITCOIN L1 ==========")
    run_onchain(nodes, workload)

    print("\n========== LIGHTNING ==========")
    run_lightning(nodes, workload)

def demo2():
    print("\n====== DEMO 2  — single 5-hop Lightning payment ======\n")

    env = simpy.Environment()

    # build A-B-C-D-E line
    nodes = [Node(env, chr(ord("A") + i)) for i in range(5)]
    for i in range(len(nodes) - 1):
        nodes[i].connect(nodes[i + 1], 2_000_000)

    print_channels(nodes, "Initial channel balances:")

    # ---- send one payment ----
    amt = 200_000
    metrics = Metrics()
    try:
        p = nodes[0].send_payment_PC(nodes[-1], amt)
        metrics.add(p)
    except ValueError as e:
        metrics.add(None)
        print(f"\nPayment failed: {e}")

    # no need to run env—send_payment already executed synchronously
    print("\n=== Lightning payment log ===")
    print(metrics.payment_log())
    print_channels(nodes, "\nFinal channel balances:")
    print("\n=== Lightning metrics ===")
    print(metrics.summary_table())


if __name__ == "__main__":
    demo()        # sequential bulk run
    demo2()       # single‐payment line demo


