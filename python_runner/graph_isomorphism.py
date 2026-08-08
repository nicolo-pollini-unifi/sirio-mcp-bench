import math
import re
import logging
import networkx as nx
from typing import Dict, Any

logger = logging.getLogger(__name__)

def is_top_failure_place(place_dict: Dict[str, Any]) -> bool:
    name = str(place_dict.get("name", "")).lower()
    if "armed" in name or "work" in name:
        return False
    return "top" in name and "fail" in name

def normalize_enabling_expression(expr: Any, place_mapping: Dict[str, str] = None) -> str:
    if not expr:
        return ""
    expr_str = str(expr).strip()
    if not expr_str:
        return ""

    or_clauses = expr_str.split("||")
    norm_or_clauses = []

    for or_clause in or_clauses:
        and_terms = or_clause.split("&&")
        norm_and_terms = []
        for term in and_terms:
            t = term.strip()
            if not t:
                continue
            m = re.match(r"^([a-zA-Z0-9_]+)\s*(==|>|=|!=)\s*([0-9]+)$", t)
            if m:
                place_name, op, val = m.group(1), m.group(2), m.group(3)
                mapped_name = place_mapping.get(place_name, place_name) if place_mapping else place_name
                if op == "!=":
                    norm_term = f"{mapped_name}:unmarked"
                else:
                    norm_term = f"{mapped_name}:marked"
            else:
                norm_term = t
                if place_mapping:
                    for k, v in place_mapping.items():
                        norm_term = re.sub(rf"\b{re.escape(k)}\b", v, norm_term)
            norm_and_terms.append(norm_term)

        norm_and_terms.sort()
        norm_or_clauses.append("&&".join(norm_and_terms))

    norm_or_clauses.sort()
    return "||".join(norm_or_clauses)

def json_to_nx_digraph(g_dict: Dict[str, Any]) -> nx.DiGraph:
    G = nx.DiGraph()

    # 1. Add Places
    for p in g_dict.get("places", []):
        name = p["name"]
        G.add_node(name,
                   node_type="place",
                   tokens=p.get("tokens", 0),
                   is_top_fail=bool(p.get("is_top_fail") or is_top_failure_place(p)))

    # 2. Add Transitions
    for t in g_dict.get("transitions", []):
        name = t["name"]
        G.add_node(name,
                   node_type="transition",
                   type=t.get("type", "immediate"),
                   rate=t.get("rate"),
                   priority=t.get("priority", 0),
                   enabling_function=t.get("enabling_function"),
                   post_updater=t.get("post_updater"))

    # 3. Add Arcs
    for arc in g_dict.get("arcs", []):
        u, v = arc["from"], arc["to"]
        G.add_edge(u, v,
                   arc_type=arc.get("type", "precondition"),
                   weight=arc.get("weight", 1))

    return G

def are_petri_nets_isomorphic(g1_dict: Dict[str, Any], g2_dict: Dict[str, Any]) -> bool:
    """
    Determines whether Petri Net graph g1 is structurally isomorphic to g2 using NetworkX.
    g1_dict and g2_dict are dictionaries with keys 'places', 'transitions', and 'arcs'.
    """
    if not isinstance(g1_dict, dict) or not isinstance(g2_dict, dict):
        return False

    G1 = json_to_nx_digraph(g1_dict)
    G2 = json_to_nx_digraph(g2_dict)

    if G1.number_of_nodes() != G2.number_of_nodes() or G1.number_of_edges() != G2.number_of_edges():
        logger.debug(f"NetworkX Isomorphism failed: node/edge count mismatch ({G1.number_of_nodes()} vs {G2.number_of_nodes()} nodes, {G1.number_of_edges()} vs {G2.number_of_edges()} edges)")
        return False

    def node_match(n1, n2):
        if n1.get('node_type') != n2.get('node_type'):
            return False

        if n1['node_type'] == 'place':
            if n1.get('tokens', 0) != n2.get('tokens', 0):
                return False
            if n1.get('is_top_fail') != n2.get('is_top_fail'):
                return False
            return True

        if n1['node_type'] == 'transition':
            if n1.get('type') != n2.get('type'):
                return False
            if n1.get('type') == 'exponential':
                r1 = n1.get('rate')
                r2 = n2.get('rate')
                if r1 is not None and r2 is not None:
                    if not math.isclose(float(r1), float(r2), rel_tol=1e-3, abs_tol=1e-5):
                        return False
            return True

        return True

    def edge_match(e1, e2):
        if e1.get('arc_type') != e2.get('arc_type'):
            return False
        return e1.get('weight', 1) == e2.get('weight', 1)

    matcher = nx.algorithms.isomorphism.DiGraphMatcher(
        G1, G2,
        node_match=node_match,
        edge_match=edge_match
    )

    if not matcher.is_isomorphic():
        logger.debug("NetworkX DiGraphMatcher returned non-isomorphic topology.")
        return False

    # Check enabling function equivalence under candidate isomorphisms
    for mapping in matcher.isomorphisms_iter():
        place_mapping = {u: v for u, v in mapping.items() if G1.nodes[u].get('node_type') == 'place'}
        all_ef_matched = True
        for t1_name, t2_name in mapping.items():
            if G1.nodes[t1_name].get('node_type') == 'transition':
                ef1 = normalize_enabling_expression(G1.nodes[t1_name].get('enabling_function'), place_mapping)
                ef2 = normalize_enabling_expression(G2.nodes[t2_name].get('enabling_function'), None)
                if ef1 != ef2:
                    all_ef_matched = False
                    break
        if all_ef_matched:
            return True

    return False
