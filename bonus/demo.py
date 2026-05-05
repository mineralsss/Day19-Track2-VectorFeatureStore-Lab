"""demo.py — 5-query script demonstrating HybridMemoryAgent capabilities.

Each query showcases a different retrieval mode:
  1. Simple lookup (vector only): "What have I read about Kubernetes?"
  2. Profile-needed: "Recommend what to read next" (uses topic_affinity)
  3. Fresh-activity: "What am I focused on lately?" (uses queries_last_hour)
  4. Paraphrase (vector wins): "Documents about scaling infrastructure?"
  5. Mixed (hybrid + profile): "Give me a cloud security summary"

Run: python bonus/demo.py
"""
from pathlib import Path

from agent import HybridMemoryAgent

# Resolve feast repo relative to project root (two levels up from bonus/)
FEAST_REPO = Path(__file__).resolve().parent.parent / "app" / "feast_repo"


def seed_memories(agent: HybridMemoryAgent) -> None:
    """Seed episodic memories so the demo has something to recall."""
    memories = [
        ("Tôi đã đọc về Kubernetes deployment patterns tuần trước", "u_001"),
        ("Document về auto-scaling trong Kubernetes cluster", "u_001"),
        ("Ghi chú về CI/CD pipeline với GitHub Actions", "u_001"),
        ("Đã xem bài về cloud security best practices hôm qua", "u_001"),
        ("Notes on PostgreSQL indexing strategies", "u_001"),
        ("Read an article about microservices communication patterns", "u_001"),
        ("Studied Terraform infrastructure-as-code for AWS", "u_001"),
        ("Watched a talk on service mesh with Istio", "u_001"),
    ]
    for text, uid in memories:
        agent.remember(text, uid)


def main() -> None:
    agent = HybridMemoryAgent(feast_repo=FEAST_REPO)
    seed_memories(agent)

    queries = [
        (
            "Simple lookup (vector only)",
            "What have I read about Kubernetes?",
        ),
        (
            "Profile-needed (uses topic_affinity)",
            "Recommend what to read next",
        ),
        (
            "Fresh-activity (uses queries_last_hour)",
            "What am I focused on lately?",
        ),
        (
            "Paraphrase (vector wins)",
            "Documents about scaling infrastructure?",
        ),
        (
            "Mixed (hybrid + profile)",
            "Give me a cloud security summary",
        ),
    ]

    for label, query in queries:
        print(f"\n{'='*60}")
        print(f"QUERY {queries.index((label, query)) + 1}: {label}")
        print(f"  > {query}")
        print("-" * 60)
        result = agent.recall(query, user_id="u_001")
        print(result)

    print(f"\n{'='*60}")
    print("Demo complete.")


if __name__ == "__main__":
    main()