#!/usr/bin/env python3
"""
Generates two .yaml.fga datasets for the Slack model:
  1) domain-only
  2) domain + agentic overlay

- Uses PyYAML to emit YAML (literal block for "model").
- Reads model files from disk (no hardcoding).
- Domain tuples are identical across both outputs; overlay file adds agent/session/scope tuples.
- Basic tests included (writer checks, list users/objects).

Examples
--------
python slack_yaml_gen_pyyaml.py \
  --model-domain ./slack_domain.fga \
  --model-overlay ./slack_overlay.fga

python slack_yaml_gen_pyyaml.py \
  --seed 7 --workspaces 2 --channels-per-ws 4 \
  --users 30 --guest-ratio 0.1 --admins-per-ws 1 \
  --writers-per-channel 2 \
  --agents 10 --sessions-per-agent 2 --write-scopes-per-channel 1 \
  --temporal-prob 0.25 --conditional-prob 0.2 \
  --out-domain slack_domain.yaml.fga --out-overlay slack_overlay.yaml.fga
"""
import argparse
import random
from typing import List, Dict, Optional, Tuple

import yaml

# ---------- YAML literal '|' helper ----------
class LiteralStr(str):
    pass

def _literal_str_representer(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

class Dumper(yaml.SafeDumper):
    pass

Dumper.add_representer(LiteralStr, _literal_str_representer)

# ---------- ID helpers ----------
def uid(i): return f"user:u{i}"
def wsid(i): return f"workspace:w{i}"
def chid(i): return f"channel:c{i}"          # <<< absolute channel id
def aid(i): return f"agent:a{i}"
def sid(i): return f"session:s{i}"
def scope_id(*parts): return "scope:" + "/".join(parts)

def emit_tuple(user: str, relation: str, obj: str, condition: Optional[dict] = None) -> dict:
    t = {"user": user, "relation": relation, "object": obj}
    if condition:
        t["condition"] = condition
    return t

def choose(seq: List[str], k: int) -> List[str]:
    k = max(0, min(k, len(seq)))
    return random.sample(seq, k) if k > 0 else []

def maybe(p: float) -> bool:
    return random.random() < p if p > 0 else False

# ---------- Domain generator ----------
def build_slack_domain(seed: int, workspaces: int, channels_per_ws: int, users: int,
                       guest_ratio: float, admins_per_ws: int, writers_per_channel: int):
    random.seed(seed)

    USERS = [uid(i) for i in range(users)]
    WSS = [wsid(i) for i in range(workspaces)]

    total_channels = max(1, workspaces * max(1, channels_per_ws))
    CHS = [chid(i) for i in range(total_channels)]

    # round-robin assign channels to workspaces
    ch_to_ws_index: Dict[str, int] = {CHS[i]: (i % workspaces) for i in range(total_channels)} if workspaces > 0 else {}

    tuples = []

    # parent_workspace edges
    for ch, wi in ch_to_ws_index.items():
        tuples.append(emit_tuple(wsid(wi), "parent_workspace", ch))

    # workspace memberships and roles
    users_per_ws = max(3, users // max(1, workspaces)) if workspaces else users
    ws_members: Dict[str, List[str]] = {}
    idx = 0
    for wi in range(workspaces):
        ws = wsid(wi)
        members = [USERS[(idx + j) % len(USERS)] for j in range(users_per_ws)]
        idx += users_per_ws
        ws_members[ws] = members

        admins = choose(members, min(admins_per_ws, len(members)))
        remaining = [m for m in members if m not in admins]
        chan_admins = choose(remaining, min(admins_per_ws, len(remaining)))

        for u in admins:
            tuples.append(emit_tuple(u, "legacy_admin", ws))
        for u in chan_admins:
            tuples.append(emit_tuple(u, "channels_admin", ws))
        for u in members:
            tuples.append(emit_tuple(u, "direct_member", ws))

        # guests
        gk = int(len(members) * guest_ratio)
        for u in choose(members, gk):
            tuples.append(emit_tuple(u, "guest", ws))

    # channel direct writers (drawn from that channel's workspace members)
    for ch, wi in ch_to_ws_index.items():
        ws = wsid(wi)
        members = ws_members.get(ws, USERS)
        writers = choose(members, min(writers_per_channel, len(members)))
        for u in writers:
            tuples.append(emit_tuple(u, "direct_writer", ch))

    return USERS, WSS, CHS, ch_to_ws_index, tuples

# ---------- Overlay generator ----------
def build_slack_overlay(seed: int, agents: int, sessions_per_agent: int,
                        write_scopes_per_channel: int, temporal_prob: float, conditional_prob: float,
                        USERS: List[str], WSS: List[str], CHS: List[str],
                        ch_to_ws_index: Dict[str, int]):
    random.seed(seed + 1)

    tuples = []
    AGENTS = [aid(i) for i in range(agents)]

    # ----- Scope tree -----
    root = scope_id("org")
    per_ws_scopes = [scope_id(f"ws{i}") for i in range(len(WSS))]
    per_ws_teams: List[str] = []
    for i, _ in enumerate(WSS):
        per_ws_teams.extend([scope_id(f"ws{i}", "team0"), scope_id(f"ws{i}", "team1")])

    # parent links: org -> ws_i; ws_i -> teams
    for ws_sc in per_ws_scopes:
        tuples.append(emit_tuple(root, "parent", ws_sc))
    for ws_i, ws_sc in enumerate(per_ws_scopes):
        tuples.append(emit_tuple(ws_sc, "parent", scope_id(f"ws{ws_i}", "team0")))
        tuples.append(emit_tuple(ws_sc, "parent", scope_id(f"ws{ws_i}", "team1")))

    ALL_SCOPES = [root] + per_ws_scopes + per_ws_teams

    # ----- Sessions per agent -----
    session_counter = 0
    AGENT_SESSIONS: Dict[str, List[str]] = {a: [] for a in AGENTS}
    for a in AGENTS:
        for _ in range(max(1, sessions_per_agent)):
            s = sid(session_counter); session_counter += 1
            AGENT_SESSIONS[a].append(s)
            tuples.append(emit_tuple(a, "actor", s))

    # ----- Attach sessions to scopes (holder) with optional temporal_access -----
    for a, sess_list in AGENT_SESSIONS.items():
        for s in sess_list:
            sc = random.choice(ALL_SCOPES)
            cond = None
            if maybe(temporal_prob):
                cond = {"name": "temporal_access",
                        "context": {"expires_at": "2030-01-01T23:59:59Z"}}
            tuples.append(emit_tuple(s, "holder", sc, condition=cond))

    # ----- Delegations (user -> agent; optionally temporal/conditional) -----
    delegation_count = max(1, len(AGENTS))
    for _ in range(delegation_count):
        a = random.choice(AGENTS)
        u = random.choice(USERS)
        cond = None
        if maybe(temporal_prob):
            cond = {"name": "temporal_delegation",
                    "context": {"expires_at": "2030-01-01T23:59:59Z"}}
        elif maybe(conditional_prob):
            cond = {"name": "conditional_delegation",
                    "context": {"allowed_purposes": ["marketing", "ops"], "purpose": "marketing"}}
        tuples.append(emit_tuple(a, "delegatee", u, condition=cond))

        # occasional agent->agent link
        if maybe(0.3):
            a2 = random.choice(AGENTS)
            if a2 != a:
                cond2 = None
                if maybe(temporal_prob):
                    cond2 = {"name": "temporal_delegation",
                             "context": {"expires_at": "2030-01-01T00:10:00Z"}}
                tuples.append(emit_tuple(a2, "delegatee", a, condition=cond2))

    # ----- Attach write_scopes to channels (per channel's workspace) -----
    for ch in CHS:
        wi = ch_to_ws_index.get(ch, 0)
        ws_sc = scope_id(f"ws{wi}")
        team_scopes = [scope_id(f"ws{wi}", "team0"), scope_id(f"ws{wi}", "team1")]
        candidate_scopes = [root, ws_sc] + team_scopes
        scopes = choose(candidate_scopes, min(max(1, write_scopes_per_channel), len(candidate_scopes)))
        for sc in scopes:
            tuples.append(emit_tuple(sc, "write_scopes", ch))

    return AGENTS, tuples

# ---------- Tests ----------
def make_domain_tests(seed: int, USERS: List[str], WSS: List[str], CHS: List[str]):
    random.seed(seed + 2)
    tests = []

    for ch in choose(CHS, min(4, len(CHS))):
        tests.append({
            "name": f"Domain writer sanity for {ch}",
            "check": [{
                "user": random.choice(USERS),
                "object": ch,
                "assertions": {"writer": random.choice([True, False])}
            }]
        })

    if CHS:
        ch = random.choice(CHS)
        tests.append({
            "name": f"Domain human writers of {ch}",
            "list_users": [{
                "object": ch,
                "user_filter": [{"type": "user"}],
                "assertions": {"writer": {"users": choose(USERS, min(5, len(USERS)))}}
            }]
        })
    return tests

def make_overlay_tests(seed: int, AGENTS: List[str], CHS: List[str]):
    random.seed(seed + 3)
    tests = []
    if not AGENTS or not CHS:
        return tests

    tests.append({
        "name": "Overlay agent writer likely-true",
        "check": [{
            "user": random.choice(AGENTS),
            "object": random.choice(CHS),
            "context": {"current_time": "2029-12-31T12:00:00Z", "purpose": "marketing"},
            "assertions": {"writer": True}
        }]
    })

    tests.append({
        "name": "Overlay agent writer likely-false",
        "check": [{
            "user": random.choice(AGENTS),
            "object": random.choice(CHS),
            "context": {"current_time": "2035-01-01T12:00:00Z", "purpose": "finance"},
            "assertions": {"writer": False}
        }]
    })

    ch = random.choice(CHS)
    tests.append({
        "name": f"Overlay agents who can write to {ch}",
        "list_users": [{
            "object": ch,
            "user_filter": [{"type": "agent"}],
            "context": {"current_time": "2029-12-31T12:00:00Z", "purpose": "marketing"},
            "assertions": {"writer": {"users": choose(AGENTS, min(4, len(AGENTS)))}}
        }]
    })
    return tests

# ---------- YAML .fga assembly ----------
def make_yaml_fga(model_text: str, tuples_list: List[dict], tests_list: List[dict], name: str) -> dict:
    return {
        "model": LiteralStr(model_text.rstrip("\n") + "\n"),
        "name": name,
        "tuples": tuples_list,
        "tests": tests_list or []
    }

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=12345)

    # Scale
    ap.add_argument("--workspaces", type=int, default=1)
    ap.add_argument("--channels-per-ws", type=int, default=3)   # fixed type
    ap.add_argument("--users", type=int, default=12)

    # Roles / membership
    ap.add_argument("--guest-ratio", type=float, default=0.1)
    ap.add_argument("--admins-per-ws", type=int, default=1)
    ap.add_argument("--writers-per-channel", type=int, default=2)

    # Overlay
    ap.add_argument("--agents", type=int, default=6)
    ap.add_argument("--sessions-per-agent", type=int, default=1)
    ap.add_argument("--write-scopes-per-channel", type=int, default=1)
    ap.add_argument("--temporal-prob", type=float, default=0.2)
    ap.add_argument("--conditional-prob", type=float, default=0.15)

    # Files
    ap.add_argument("--model-domain", required=True, help="Path to domain model .fga")
    ap.add_argument("--model-overlay", required=True, help="Path to overlay model .fga")
    ap.add_argument("--out-domain", default="slack_domain.fga.yaml")
    ap.add_argument("--out-overlay", default="slack_overlay.fga.yaml")

    args = ap.parse_args()

    # Load models
    with open(args.model_domain, "r", encoding="utf-8") as f:
        model_domain_text = f.read()
    with open(args.model_overlay, "r", encoding="utf-8") as f:
        model_overlay_text = f.read()

    # Domain
    USERS, WSS, CHS, ch_to_ws_index, tuples_domain = build_slack_domain(
        seed=args.seed,
        workspaces=args.workspaces,
        channels_per_ws=args.channels_per_ws,
        users=args.users,
        guest_ratio=args.guest_ratio,
        admins_per_ws=args.admins_per_ws,
        writers_per_channel=args.writers_per_channel,
    )
    tests_domain = make_domain_tests(args.seed, USERS, WSS, CHS)

    # Overlay extras
    AGENTS, tuples_overlay = build_slack_overlay(
        seed=args.seed,
        agents=args.agents,
        sessions_per_agent=args.sessions_per_agent,
        write_scopes_per_channel=args.write_scopes_per_channel,
        temporal_prob=args.temporal_prob,
        conditional_prob=args.conditional_prob,
        USERS=USERS, WSS=WSS, CHS=CHS, ch_to_ws_index=ch_to_ws_index,
    )
    tests_overlay = tests_domain + make_overlay_tests(args.seed, AGENTS, CHS)

    # Assemble and dump
   # domain_obj = make_yaml_fga(model_domain_text, tuples_domain, tests_domain, name="Slack (domain)")
   # overlay_obj = make_yaml_fga(model_overlay_text, tuples_domain + tuples_overlay, tests_overlay, name="Slack (overlay)")

    with open(args.out_domain, "w", encoding="utf-8") as f:
        yaml.dump(tuples_domain, f, Dumper=Dumper, sort_keys=False, allow_unicode=True)
    with open(args.out_overlay, "w", encoding="utf-8") as f:
        yaml.dump(tuples_domain + tuples_overlay, f, Dumper=Dumper, sort_keys=False, allow_unicode=True)

    print(f"Wrote {args.out_domain} and {args.out_overlay}")

if __name__ == "__main__":
    main()
