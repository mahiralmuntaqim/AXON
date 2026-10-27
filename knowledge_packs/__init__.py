"""CTF/pentest knowledge packs — source content for the agent knowledge graph.

The Python-importable surface is intentionally thin: the packs themselves are
data files (``packs/<category>/{tools.json,playbook.md,resources.md}``). The
loader that turns them into an in-process knowledge graph lives in
``security_agents.knowledge_graph``.
"""
