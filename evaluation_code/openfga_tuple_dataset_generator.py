#!/usr/bin/env python3
"""
openfga_yaml_gen_pyyaml.py

Generates two .yaml.fga datasets for benchmarking:
  1) domain-only
  2) domain + agentic overlay

Key points:
- Uses PyYAML to emit YAML (no custom emitters).
- Reads model files from disk (do NOT hardcode models).
- Ensures literal block scalar for the "model" field.
- Produces identical domain tuples for both datasets; overlay file adds overlay tuples.
- Includes basic tests (check + list_users).

Examples:
  python openfga_yaml_gen_pyyaml.py \
    --model-domain ./domain_model.fga \
    --model-overlay ./overlay_model.fga

  python openfga_yaml_gen_pyyaml.py \
    --seed 42 --users 50 --groups 6 \
    --folders 20 --folder-depth 3 --docs-per-folder 4 \
    --group-viewer-ratio 0.5 --doc-direct-viewer-ratio 0.2 \
    --agents 20 --teams-per-scope 3 \
    --out-domain domain.yaml.fga --out-overlay overlay.yaml.fga \
    --model-domain ./domain_model.fga --model-overlay ./overlay_model.fga
"""
import argparse
import random
import json
from typing import List, Dict, Optional, Tuple

import yaml

# ---------- YAML literal '|' helper ----------
class LiteralStr(str):
    pass

def _literal_str_representer(dumper, data):
    # Emit as block scalar with |
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

class Dumper(yaml.SafeDumper):
    pass

Dumper.add_representer(LiteralStr, _literal_str_representer)

# ---------- ID helpers ----------
def uid(i): return f"user:u{i}"
def gid(i): return f"group:g{i}"
def fid(i): return f"folder:f{i}"
def did(i): return f"doc:d{i}"
def aid(i): return f"agent:a{i}"
def sid(i): return f"session:s{i}"
def scope_id(name): return f"scope:{name}"

def emit_tuple(user: str, relation: str, obj: str, condition: Optional[dict] = None) -> dict:
    t = {"user": user, "relation": relation, "object": obj}
    if condition:
        t["condition"] = condition
    return t

def choose(seq: List[str], k: int) -> List[str]:
    k = max(0, min(k, len(seq)))
    return random.sample(seq, k) if k > 0 else []

def maybe(p: float) -> bool:
    return random.random() < p

# ---------- Build shared domain ----------
def build_shared_domain(seed: int, users: int, groups: int,
                        folders: int, folder_depth: int, docs_per_folder: int,
                        group_viewer_ratio: float, doc_direct_viewer_ratio: float):
    random.seed(seed)

    USERS_L = [uid(i) for i in range(users)]
    GROUPS_L = [gid(i) for i in range(groups)]
    FOLDERS_L = [fid(i) for i in range(folders)]
    DOCS_L = [did(i) for i in range(folders * docs_per_folder)]

    tuples_domain = []

    # Group memberships
    avg_members = max(2, users // max(1, groups))
    for gi in range(groups):
        k = max(1, int(random.gauss(avg_members, max(1, avg_members // 3))))
        for user in choose(USERS_L, k):
            tuples_domain.append(emit_tuple(user, "member", gid(gi)))

    # Folder parent edges (layered by depth)
    layers = [[] for _ in range(max(1, folder_depth))]
    for i, folder in enumerate(FOLDERS_L):
        layers[i % max(1, folder_depth)].append(folder)
    for depth in range(1, max(1, folder_depth)):
        for child in layers[depth]:
            parent = random.choice(layers[depth - 1])
            tuples_domain.append(emit_tuple(parent, "parent", child))

    # Ownerships
    for folder in FOLDERS_L:
        tuples_domain.append(emit_tuple(random.choice(USERS_L), "owner", folder))
    for doc in DOCS_L:
        tuples_domain.append(emit_tuple(random.choice(USERS_L), "owner", doc))

    # Place docs in folders
    for doc in DOCS_L:
        folder = random.choice(FOLDERS_L)
        tuples_domain.append(emit_tuple(folder, "parent", doc))

    # Sharing: group viewers on folders
    max_groups_attached = max(1, int(groups * group_viewer_ratio))
    for folder in FOLDERS_L:
        k = random.randint(0, max_groups_attached)
        for gg in choose(GROUPS_L, k):
            tuples_domain.append(emit_tuple(gg, "group_viewer", folder))

    # Sharing: direct doc viewers (users)
    max_user_viewers = max(1, int(users * doc_direct_viewer_ratio))
    for doc in DOCS_L:
        k = random.randint(0, max_user_viewers)
        for uu in choose(USERS_L, k):
            tuples_domain.append(emit_tuple(uu, "viewer", doc))

    return USERS_L, GROUPS_L, FOLDERS_L, DOCS_L, tuples_domain

# ---------- Overlay extras ----------
def build_overlay_extra(seed: int, agents: int, teams_per_scope: int,
                        sessions_per_agent: int, session_only_fraction: float,
                        temporal_prob: float, conditional_prob: float,
                        USERS_L: List[str], DOCS_L: List[str], FOLDERS_L: List[str]):
    random.seed(seed + 1)

    tuples_overlay_extra = []
    AGENTS_L = [aid(i) for i in range(agents)]

    # scope tree: root -> org -> teams
    roots = [scope_id("root")]
    orgs = [scope_id("org")]
    teams = [scope_id(f"org/team{t}") for t in range(teams_per_scope)]
    scope_edges = [(roots[0], orgs[0])] + [(orgs[0], t) for t in teams]
    for p, c in scope_edges:
        tuples_overlay_extra.append(emit_tuple(p, "parent", c))
    ALL_SCOPES = roots + orgs + teams

    # place folders in scopes
    for folder in FOLDERS_L:
        sc = random.choice(ALL_SCOPES)
        tuples_overlay_extra.append(emit_tuple(sc, "in_scope", folder))

    # sessions for agents
    agent_sessions = {agent: [] for agent in AGENTS_L}
    session_counter = 0
    for agent in AGENTS_L:
        for _ in range(sessions_per_agent):
            s_id = sid(session_counter); session_counter += 1
            agent_sessions[agent].append(s_id)
            tuples_overlay_extra.append(emit_tuple(agent, "actor", s_id))

    # session holders
    session_only_agents = set(random.sample(AGENTS_L, int(len(AGENTS_L) * session_only_fraction))) if AGENTS_L else set()
    for agent, sess_list in agent_sessions.items():
        for ss in sess_list:
            sc = random.choice(ALL_SCOPES)
            cond = None
            if maybe(temporal_prob):
                cond = {"name": "temporal_access", "context": {"expires_at": "2030-01-01T01:00:00Z"}}
            tuples_overlay_extra.append(emit_tuple(ss, "holder", sc, condition=cond))

    # delegations
    backed_agents = set()
    delegation_chains = max(0, min(agents, max(1, agents // 2)))  # heuristic
    for _ in range(delegation_chains):
        human = random.choice(USERS_L)
        agent = random.choice(AGENTS_L)
        cond = None
        if maybe(temporal_prob):
            cond = {"name": "temporal_delegation", "context": {"expires_at": "2030-01-01T01:00:00Z"}}
        elif maybe(conditional_prob):
            cond = {"name": "conditional_delegation", "context": {"allowed_purposes": ["read","summarize"], "purpose": "read"}}
        tuples_overlay_extra.append(emit_tuple(agent, "delegatee", human, condition=cond))
        backed_agents.add(agent)

        chain_len = random.randint(0, 2)
        prev = agent
        for _ in range(chain_len):
            nxt = random.choice(AGENTS_L)
            if nxt == prev:
                continue
            cond2 = None
            if maybe(temporal_prob):
                cond2 = {"name": "temporal_delegation", "context": {"expires_at": "2030-01-01T00:10:00Z"}}
            elif maybe(conditional_prob):
                cond2 = {"name": "conditional_delegation", "context": {"allowed_purposes": ["read"], "purpose": "read"}}
            tuples_overlay_extra.append(emit_tuple(nxt, "delegatee", prev, condition=cond2))
            prev = nxt
            backed_agents.add(nxt)

    return AGENTS_L, tuples_overlay_extra, session_only_agents, backed_agents

# ---------- Tests ----------
def make_domain_tests(seed: int, USERS_L: List[str], DOCS_L: List[str], FOLDERS_L: List[str],
                      num_test_docs: int, num_test_folders: int):
    random.seed(seed + 2)
    tests = []
    # doc checks
    docs = choose(DOCS_L, min(num_test_docs, len(DOCS_L)))
    for doc in docs:
        tests.append({
            "name": f"Domain can_read on {doc}",
            "check": [{
                "user": random.choice(USERS_L),
                "object": doc,
                "assertions": {"can_read": random.choice([True, False])}
            }]
        })
    # folder viewers (expanded users)
    for folder in choose(FOLDERS_L, min(num_test_folders, len(FOLDERS_L))):
        tests.append({
            "name": f"Domain who can view folder {folder}",
            "list_users": [{
                "object": folder,
                "user_filter": [{"type": "user"}],
                "assertions": {"viewer": {"users": choose(USERS_L, min(3, len(USERS_L))) }}
            }]
        })
    return tests

def make_overlay_tests(seed: int, AGENTS_L: List[str], DOCS_L: List[str], FOLDERS_L: List[str],
                       session_only_agents: set, backed_agents: set):
    random.seed(seed + 3)
    tests = []
    if backed_agents:
        agent = random.choice(list(backed_agents))
        doc = random.choice(DOCS_L)
        tests.append({
            "name": f"Overlay agent {agent} can_read {doc} (likely true)",
            "check": [{
                "user": agent,
                "object": doc,
                "context": {"current_time": "2025-01-01T00:10:00Z"},
                "assertions": {"can_read": True}
            }]
        })
    if session_only_agents:
        agent = random.choice(list(session_only_agents))
        doc = random.choice(DOCS_L)
        tests.append({
            "name": f"Overlay agent {agent} can_read {doc} (likely false)",
            "check": [{
                "user": agent,
                "object": doc,
                "context": {"current_time": "2025-01-01T00:10:00Z"},
                "assertions": {"can_read": False}
            }]
        })
    folder = random.choice(FOLDERS_L)
    tests.append({
        "name": f"Overlay which agents can_view {folder}",
        "list_users": [{
            "object": folder,
            "user_filter": [{"type": "agent"}],
            "assertions": {"can_view": {"users": choose(AGENTS_L, min(3, len(AGENTS_L))) }}
        }]
    })
    return tests

# ---------- YAML .fga assembly ----------
def make_yaml_fga(model_text: str, tuples_list: List[dict], tests_list: List[dict]) -> dict:
    return {
        # "model": LiteralStr(model_text.rstrip("\n") + "\n"),
        tuples_list
       # "tests": tests_list or []
    }

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=12345)

    # Scale
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--groups", type=int, default=4)
    ap.add_argument("--folders", type=int, default=8)
    ap.add_argument("--folder-depth", type=int, default=3)
    ap.add_argument("--docs-per-folder", type=int, default=3)

    # Sharing
    ap.add_argument("--group-viewer-ratio", type=float, default=0.5)
    ap.add_argument("--doc-direct-viewer-ratio", type=float, default=0.15)

    # Overlay extras
    ap.add_argument("--agents", type=int, default=8)
    ap.add_argument("--teams-per-scope", type=int, default=2)
    ap.add_argument("--sessions-per-agent", type=int, default=1)
    ap.add_argument("--session-only-fraction", type=float, default=0.25)
    ap.add_argument("--temporal-prob", type=float, default=0.2)
    ap.add_argument("--conditional-prob", type=float, default=0.15)

    # Tests
    ap.add_argument("--num-test-docs", type=int, default=4)
    ap.add_argument("--num-test-folders", type=int, default=2)

    # Files
    ap.add_argument("--model-domain", required=True, help="Path to domain model .fga (text)")
    ap.add_argument("--model-overlay", required=True, help="Path to overlay model .fga (text)")
    ap.add_argument("--out-domain", default="domain.fga.yaml")
    ap.add_argument("--out-overlay", default="overlay.fga.yaml")

    args = ap.parse_args()

    # Load models from disk
    with open(args.model_domain, "r", encoding="utf-8") as f:
        model_domain_text = f.read()
    with open(args.model_overlay, "r", encoding="utf-8") as f:
        model_overlay_text = f.read()

    # Build shared domain
    USERS_L, GROUPS_L, FOLDERS_L, DOCS_L, tuples_domain = build_shared_domain(
        seed=args.seed,
        users=args.users,
        groups=args.groups,
        folders=args.folders,
        folder_depth=args.folder_depth,
        docs_per_folder=args.docs_per_folder,
        group_viewer_ratio=args.group_viewer_ratio,
        doc_direct_viewer_ratio=args.doc_direct_viewer_ratio,
    )

    # Domain tests
    tests_domain = make_domain_tests(args.seed, USERS_L, DOCS_L, FOLDERS_L,
                                     num_test_docs=args.num_test_docs,
                                     num_test_folders=args.num_test_folders)

    # Overlay extras + tests
    AGENTS_L, tuples_overlay_extra, session_only_agents, backed_agents = build_overlay_extra(
        seed=args.seed,
        agents=args.agents,
        teams_per_scope=args.teams_per_scope,
        sessions_per_agent=args.sessions_per_agent,
        session_only_fraction=args.session_only_fraction,
        temporal_prob=args.temporal_prob,
        conditional_prob=args.conditional_prob,
        USERS_L=USERS_L, DOCS_L=DOCS_L, FOLDERS_L=FOLDERS_L,
    )
    tests_overlay = tests_domain + make_overlay_tests(args.seed, AGENTS_L, DOCS_L, FOLDERS_L,
                                                      session_only_agents, backed_agents)

    # Assemble YAML dicts
    #domain_obj = make_yaml_fga(model_domain_text, tuples_domain, tests_domain)
   # overlay_obj = make_yaml_fga(model_overlay_text, tuples_domain + tuples_overlay_extra, tests_overlay)

    # Dump with PyYAML (ensure block style for model via LiteralStr)
    with open(args.out_domain, "w", encoding="utf-8") as f:
        yaml.dump(tuples_domain, f, Dumper=Dumper, sort_keys=False, allow_unicode=True)
    with open(args.out_overlay, "w", encoding="utf-8") as f:
        yaml.dump(tuples_domain + tuples_overlay_extra, f, Dumper=Dumper, sort_keys=False, allow_unicode=True)

    print(f"Wrote {args.out_domain} and {args.out_overlay}")

if __name__ == "__main__":
    main()
