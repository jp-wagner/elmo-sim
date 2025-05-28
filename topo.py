import random
from typing import List
from lightning import Node, SAT
import networkx as nx
import matplotlib.pyplot as plt

def export_topology_png(nodes: List[Node],
                        path: str = "topology.png",
                        seed: int = 42) -> None:
    """
    Draw the channel graph with NetworkX + matplotlib.
    """

    G = nx.Graph()
    for n in nodes:
        G.add_node(n.name)
    seen = set()
    for n in nodes:
        for peer in n.channels:
            # undirected edge, add once
            if (n, peer) in seen or (peer, n) in seen:
                continue
            G.add_edge(n.name, peer.name)
            seen.add((n, peer))

    pos = nx.spring_layout(G, seed=seed)  # deterministic layout
    plt.figure(figsize=(8, 8))
    nx.draw(G, pos,
            node_size=350, node_color="#ffcc00",
            edgecolors="black", linewidths=0.8,
            with_labels=True, font_size=8)
    plt.savefig(path, dpi=300)
    plt.close()
    print(f"[topology] saved {path}")


def generate_LN_topology(env,
                              num_nodes: int = 100,
                              m: int = 2,
                              base_capacity: SAT = 2_000_000,
                              ppm_variance: int = 1000,
                              *,
                              draw_png: bool = False) -> List[Node]:

    assert m >= 1, "need at least one connection per new node"

    # initial clique
    nodes: List[Node] = [Node(env, f"N{i}") for i in range(m + 1)]
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            nodes[i].connect(nodes[j], base_capacity)

    degree_bag: List[Node] = []
    for n in nodes:
        degree_bag.extend([n] * len(n.channels))

    # preferential-attachment growth 
    for idx in range(m + 1, num_nodes):
        new_node = Node(env, f"N{idx}")

        targets = set()
        while len(targets) < m:
            targets.add(random.choice(degree_bag))

        for t in targets:
            capacity = base_capacity
            ppm = random.randint(1, 1 + ppm_variance)
            t.connect(new_node, capacity)
            t.channels[new_node].policy.fee_rate_ppm = ppm
            degree_bag.extend([t, new_node])

        nodes.append(new_node)

    if draw_png:
        export_topology_png(nodes)

    return nodes

