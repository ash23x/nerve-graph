#!/usr/bin/env python3
"""
nerve-graph: build_vault_data.py
Scans a folder of [[wikilinked]] markdown files and generates vault_data.js
for the 3D topology visualiser.

Usage:
    python build_vault_data.py                    # uses config.json
    python build_vault_data.py /path/to/vault     # override vault path

Works with: Obsidian, Logseq, Dendron, Foam, Zettlr, or any folder of .md files.

Dependencies: pip install networkx pyyaml
"""
import os, re, json, sys, math, time

try:
    import networkx as nx
except ImportError:
    print("Installing networkx...")
    os.system(f'"{sys.executable}" -m pip install networkx')
    import networkx as nx

try:
    import yaml
except ImportError:
    print("Installing pyyaml...")
    os.system(f'"{sys.executable}" -m pip install pyyaml')
    import yaml

# ── CONFIG ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')

def load_config():
    defaults = {
        "vault_path": ".",
        "vault_name": "MyVault",
        "output": "vault_data.js",
        "skip_dirs": [".obsidian", ".git", "node_modules", ".trash"],
        "root_exponent": 0.2,
        "boost": 0.3,
        "custom_domains": {}
    }
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            user = json.load(f)
        defaults.update(user)
    return defaults

config = load_config()

# CLI override
if len(sys.argv) > 1:
    config['vault_path'] = sys.argv[1]

VAULT = os.path.abspath(config['vault_path'])
OUTPUT = os.path.join(SCRIPT_DIR, config['output'])
SKIP_DIRS = set(config['skip_dirs'])
ROOT_EXP = config['root_exponent']  # 0.2 = fifth root
BOOST = config['boost']

# ── AUTO-DISCOVERED COLOUR PALETTE ──
# 14 visually distinct colours for auto-assignment
AUTO_PALETTE = [
    '#58a6ff', '#ff9100', '#ff1744', '#00e5ff', '#00e676',
    '#76ff03', '#ff4081', '#ffd740', '#d500f9', '#ff6e40',
    '#448aff', '#ffea00', '#b0bec5', '#78909c'
]
AUTO_SHAPES = [
    'icosahedron', 'cube', 'dodecahedron', 'octahedron',
    'torus', 'tetrahedron', 'torusknot', 'cone'
]
DEFAULT_STYLE = {'color': '#888888', 'shape': 'icosahedron'}

# ── HELPERS ──
WIKILINK_RE = re.compile(r'\[\[([^\]|#]+)(?:#[^\]|]*)?\|?[^\]]*\]\]')
FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)

def extract_frontmatter(text):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except:
        return {}

def get_cluster(fm):
    """Extract cluster/domain from frontmatter."""
    cluster = fm.get('cluster', '').strip().lower()
    if cluster:
        return cluster
    tags = fm.get('tags', [])
    if isinstance(tags, str):
        tags = [t.strip().lstrip('#').lower() for t in tags.split(',')]
    if isinstance(tags, list):
        for t in tags:
            t = str(t).strip().lstrip('#').lower()
            if t and t not in ('meta', 'system', 'dashboard'):
                return t
    return 'general'

# ── MAIN SCAN ──
print(f"nerve-graph: scanning {VAULT}")
now = time.time()
G = nx.DiGraph()
note_meta = {}
note_basenames = {}
cluster_set = set()

# Pass 1: discover all notes
for root, dirs, files in os.walk(VAULT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for fname in files:
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(root, fname)
        relpath = os.path.relpath(fpath, VAULT)
        basename = os.path.splitext(fname)[0]
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
            mtime = os.path.getmtime(fpath)
        except:
            continue
        fm = extract_frontmatter(text)
        cluster = get_cluster(fm)
        cluster_set.add(cluster)
        G.add_node(basename)
        note_meta[basename] = {'cluster': cluster, 'mtime': mtime, 'relpath': relpath}
        note_basenames[basename.lower()] = basename

print(f"  Pass 1: {G.number_of_nodes()} notes, {len(cluster_set)} clusters discovered")

# Pass 2: extract links
for root, dirs, files in os.walk(VAULT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for fname in files:
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(root, fname)
        basename = os.path.splitext(fname)[0]
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
        except:
            continue
        for raw in WIKILINK_RE.findall(text):
            target = raw.strip()
            if '/' in target:
                target = target.split('/')[-1]
            tl = target.lower()
            if tl in note_basenames and note_basenames[tl] != basename:
                G.add_edge(basename, note_basenames[tl])

print(f"  Pass 2: {G.number_of_edges()} edges extracted")

# ── ASSIGN COLOURS TO CLUSTERS ──
# User-defined domains override auto-assignment
custom = config.get('custom_domains', {})
cluster_style = {}
auto_idx = 0
for cluster in sorted(cluster_set):
    if cluster in custom:
        cluster_style[cluster] = custom[cluster]
    else:
        cluster_style[cluster] = {
            'color': AUTO_PALETTE[auto_idx % len(AUTO_PALETTE)],
            'shape': AUTO_SHAPES[auto_idx % len(AUTO_SHAPES)]
        }
        auto_idx += 1

# ── COMPUTE METRICS ──
print("  Computing betweenness centrality...")
bc = nx.betweenness_centrality(G)
degree = dict(G.degree())
edge_set = set(G.edges())

# ── NORMALISATION ──
all_mtimes = [m['mtime'] for m in note_meta.values()]
mtime_min, mtime_max = min(all_mtimes), max(all_mtimes)
mtime_range = max(mtime_max - mtime_min, 1)
bc_max = max(bc.values()) if bc.values() else 1
bc_max = max(bc_max, 0.0001)

def recency(mt):
    return round((mt - mtime_min) / mtime_range, 4)

def norm_bet(b):
    if b <= 0:
        return 0.0
    return round(min(1.0, (b / bc_max) ** ROOT_EXP + BOOST), 4)

# ── BUILD OUTPUT ──
nodes_out = []
for nid in G.nodes():
    meta = note_meta.get(nid, {'cluster': 'general', 'mtime': now})
    style = cluster_style.get(meta['cluster'], DEFAULT_STYLE)
    deg = degree.get(nid, 0)
    nodes_out.append({
        'id': nid,
        'color': style['color'],
        'shape': style.get('shape', 'icosahedron'),
        'degree': deg,
        'betweenness': norm_bet(bc.get(nid, 0)),
        'recency': recency(meta['mtime']),
        'cluster': meta['cluster'],
    })

edges_out = []
seen = set()
for src, tgt in G.edges():
    key = (src, tgt)
    if key not in seen:
        bidir = (tgt, src) in edge_set
        tgt_meta = note_meta.get(tgt, {'cluster': 'general', 'mtime': now})
        src_meta = note_meta.get(src, {'cluster': 'general', 'mtime': now})
        tgt_style = cluster_style.get(tgt_meta['cluster'], DEFAULT_STYLE)
        tgt_rec = recency(tgt_meta['mtime'])
        src_rec = recency(src_meta['mtime'])
        edge_rec = round(min(src_rec, tgt_rec), 4)
        edges_out.append({
            'from': src, 'to': tgt, 'bidir': bidir,
            'tColor': tgt_style['color'], 'tRec': tgt_rec, 'eRec': edge_rec,
        })
        seen.add(key)
        if bidir:
            seen.add((tgt, src))

# ── BUILD DOMAIN MAP for HTML consumption ──
domain_map = {}
for cluster, style in cluster_style.items():
    domain_map[style['color']] = {
        'label': cluster.replace('-', ' ').title(),
        'shape': style.get('shape', 'icosahedron'),
    }

# ── WRITE vault_data.js ──
js = 'var VAULT_NAME = ' + json.dumps(config['vault_name']) + ';\n'
js += 'var DOMAIN_MAP_DATA = ' + json.dumps(domain_map, ensure_ascii=False) + ';\n'
js += 'const VAULT_NODES = ' + json.dumps(nodes_out, ensure_ascii=False) + ';\n'
js += 'const VAULT_EDGES = ' + json.dumps(edges_out, ensure_ascii=False) + ';\n'

with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(js)

# ── STATS ──
bidir_count = sum(1 for e in edges_out if e['bidir'])
print(f"\n  Done! Written to: {OUTPUT}")
print(f"  Nodes: {len(nodes_out)}")
print(f"  Edges: {len(edges_out)}  ({bidir_count} bidirectional, {len(edges_out)-bidir_count} one-way)")
print(f"  Clusters: {len(cluster_style)}")
print(f"  Recency range: {mtime_range/86400:.1f} days")
print(f"\n  Cluster breakdown:")
for cluster in sorted(cluster_style.keys()):
    count = sum(1 for n in nodes_out if n['cluster'] == cluster)
    style = cluster_style[cluster]
    print(f"    {cluster:30s}  {count:4d} notes  {style['color']}")
print(f"\n  Top 10 hubs:")
for name, deg in sorted(degree.items(), key=lambda x: -x[1])[:10]:
    print(f"    {name:50s}  deg={deg}")
print(f"\n  Open nerve_graph.html in your browser to explore.")
