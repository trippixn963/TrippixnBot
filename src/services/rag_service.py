"""
TrippixnBot - RAG (Retrieval Augmented Generation) Service
==========================================================

Vector-based knowledge retrieval for intelligent AI responses.
Uses ChromaDB for persistent vector storage and OpenAI embeddings.

Author: حَـــــنَّـــــا
"""

import asyncio
import time
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import chromadb
from chromadb.config import Settings
from openai import OpenAI

from src.core import config, log


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class RetrievedContext:
    """Context retrieved from vector search."""
    content: str
    metadata: dict
    relevance: float
    source: str  # 'knowledge', 'message', 'user', 'channel'


# =============================================================================
# RAG Service
# =============================================================================

class RAGService:
    """
    Retrieval Augmented Generation service.

    Stores and retrieves relevant context using vector embeddings.
    Much more efficient than sending full server context every time.
    """

    EMBEDDING_MODEL = "text-embedding-3-small"
    DATA_DIR = Path(__file__).parent.parent.parent / "data" / "rag"

    # Collection names
    KNOWLEDGE_COLLECTION = "knowledge"      # FAQs, rules, channel descriptions
    MESSAGES_COLLECTION = "messages"        # Recent messages for context
    USERS_COLLECTION = "users"              # User information and patterns

    def __init__(self):
        self.openai_client: Optional[OpenAI] = None
        self.chroma_client: Optional[chromadb.PersistentClient] = None
        self.collections: dict = {}
        self._initialized = False

    async def setup(self) -> bool:
        """Initialize the RAG service."""
        if not config.OPENAI_API_KEY:
            log.tree("RAG Service Disabled", [
                ("Reason", "No OpenAI API key"),
            ], emoji="⚠️")
            return False

        try:
            # Initialize OpenAI client for embeddings
            self.openai_client = OpenAI(api_key=config.OPENAI_API_KEY)

            # Create data directory
            self.DATA_DIR.mkdir(parents=True, exist_ok=True)

            # Initialize ChromaDB with persistence
            self.chroma_client = chromadb.PersistentClient(
                path=str(self.DATA_DIR),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                )
            )

            # Get or create collections
            self.collections[self.KNOWLEDGE_COLLECTION] = self.chroma_client.get_or_create_collection(
                name=self.KNOWLEDGE_COLLECTION,
                metadata={"description": "Server knowledge, FAQs, rules"}
            )
            self.collections[self.MESSAGES_COLLECTION] = self.chroma_client.get_or_create_collection(
                name=self.MESSAGES_COLLECTION,
                metadata={"description": "Recent messages for context"}
            )
            self.collections[self.USERS_COLLECTION] = self.chroma_client.get_or_create_collection(
                name=self.USERS_COLLECTION,
                metadata={"description": "User information"}
            )

            self._initialized = True

            # Log stats
            knowledge_count = self.collections[self.KNOWLEDGE_COLLECTION].count()
            messages_count = self.collections[self.MESSAGES_COLLECTION].count()
            users_count = self.collections[self.USERS_COLLECTION].count()

            log.tree("RAG Service Initialized", [
                ("Knowledge Items", str(knowledge_count)),
                ("Messages Indexed", str(messages_count)),
                ("Users Tracked", str(users_count)),
                ("Data Path", str(self.DATA_DIR)),
            ], emoji="🧠")

            return True

        except Exception as e:
            log.error_tree("RAG Service Setup Failed", e)
            return False

    @property
    def is_available(self) -> bool:
        """Check if RAG service is available."""
        return self._initialized and self.openai_client is not None

    def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using OpenAI."""
        if not self.openai_client:
            return []

        try:
            response = self.openai_client.embeddings.create(
                model=self.EMBEDDING_MODEL,
                input=text[:8000],  # Limit input length
            )
            return response.data[0].embedding
        except Exception as e:
            log.tree("Embedding Failed", [
                ("Error", str(e)[:50]),
            ], emoji="❌")
            return []

    # =========================================================================
    # Knowledge Management (FAQs, Rules, Channel Info)
    # =========================================================================

    def add_knowledge(self, content: str, category: str, metadata: dict = None) -> bool:
        """
        Add knowledge to the vector store.

        Args:
            content: The knowledge content (FAQ answer, rule, etc.)
            category: Type of knowledge (faq, rule, channel, role, etc.)
            metadata: Additional metadata
        """
        if not self.is_available:
            return False

        try:
            embedding = self._get_embedding(content)
            if not embedding:
                return False

            doc_id = f"{category}_{hash(content) % 100000}"

            meta = {
                "category": category,
                "timestamp": time.time(),
                **(metadata or {})
            }

            self.collections[self.KNOWLEDGE_COLLECTION].upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[meta]
            )

            log.tree("Knowledge Added", [
                ("Category", category),
                ("Content", content[:50] + "..." if len(content) > 50 else content),
            ], emoji="📚")

            return True

        except Exception as e:
            log.error_tree("Add Knowledge Failed", e)
            return False

    def add_faq(self, question: str, answer: str) -> bool:
        """Add a FAQ entry."""
        content = f"Q: {question}\nA: {answer}"
        return self.add_knowledge(content, "faq", {"question": question})

    def add_channel_info(self, channel_name: str, description: str) -> bool:
        """Add channel description."""
        content = f"#{channel_name}: {description}"
        return self.add_knowledge(content, "channel", {"channel": channel_name})

    def add_role_info(self, role_name: str, description: str) -> bool:
        """Add role description."""
        content = f"@{role_name}: {description}"
        return self.add_knowledge(content, "role", {"role": role_name})

    def add_rule(self, rule_number: int, rule_text: str) -> bool:
        """Add a server rule."""
        content = f"Rule {rule_number}: {rule_text}"
        return self.add_knowledge(content, "rule", {"rule_number": rule_number})

    # =========================================================================
    # Message Indexing
    # =========================================================================

    def index_message(
        self,
        message_id: int,
        content: str,
        author_name: str,
        author_id: int,
        channel_name: str,
        channel_id: int,
    ) -> bool:
        """Index a message for future retrieval."""
        if not self.is_available:
            return False

        # Skip very short messages
        if len(content) < 10:
            return False

        try:
            embedding = self._get_embedding(content)
            if not embedding:
                return False

            doc_id = f"msg_{message_id}"

            self.collections[self.MESSAGES_COLLECTION].upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[{
                    "author_name": author_name,
                    "author_id": str(author_id),
                    "channel_name": channel_name,
                    "channel_id": str(channel_id),
                    "timestamp": time.time(),
                }]
            )

            return True

        except Exception as e:
            log.tree("Message Index Failed", [
                ("Error", str(e)[:50]),
            ], emoji="⚠️")
            return False

    # =========================================================================
    # User Tracking
    # =========================================================================

    def update_user(
        self,
        user_id: int,
        username: str,
        display_name: str,
        roles: list[str],
        summary: str = None,
    ) -> bool:
        """Update user information in the vector store."""
        if not self.is_available:
            return False

        try:
            content = f"User: {display_name} (@{username})\n"
            content += f"Roles: {', '.join(roles)}\n"
            if summary:
                content += f"About: {summary}"

            embedding = self._get_embedding(content)
            if not embedding:
                return False

            doc_id = f"user_{user_id}"

            self.collections[self.USERS_COLLECTION].upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[{
                    "user_id": str(user_id),
                    "username": username,
                    "display_name": display_name,
                    "roles": ",".join(roles),
                    "timestamp": time.time(),
                }]
            )

            return True

        except Exception as e:
            log.tree("User Update Failed", [
                ("User ID", str(user_id)),
                ("Error", str(e)[:50]),
            ], emoji="⚠️")
            return False

    # =========================================================================
    # Retrieval
    # =========================================================================

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        collections: list[str] = None,
    ) -> list[RetrievedContext]:
        """
        Retrieve relevant context for a query.

        Args:
            query: The search query
            n_results: Number of results per collection
            collections: Which collections to search (default: all)

        Returns:
            List of RetrievedContext objects sorted by relevance
        """
        if not self.is_available:
            return []

        if collections is None:
            collections = [self.KNOWLEDGE_COLLECTION, self.MESSAGES_COLLECTION, self.USERS_COLLECTION]

        try:
            query_embedding = self._get_embedding(query)
            if not query_embedding:
                return []

            results = []

            for collection_name in collections:
                if collection_name not in self.collections:
                    continue

                collection = self.collections[collection_name]

                # Skip empty collections
                if collection.count() == 0:
                    continue

                search_results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=min(n_results, collection.count()),
                    include=["documents", "metadatas", "distances"]
                )

                if not search_results["documents"] or not search_results["documents"][0]:
                    continue

                for i, doc in enumerate(search_results["documents"][0]):
                    # Convert distance to relevance (lower distance = higher relevance)
                    distance = search_results["distances"][0][i] if search_results["distances"] else 1.0
                    relevance = 1.0 / (1.0 + distance)

                    results.append(RetrievedContext(
                        content=doc,
                        metadata=search_results["metadatas"][0][i] if search_results["metadatas"] else {},
                        relevance=relevance,
                        source=collection_name,
                    ))

            # Sort by relevance
            results.sort(key=lambda x: x.relevance, reverse=True)

            log.tree("RAG Retrieval", [
                ("Query", query[:40] + "..." if len(query) > 40 else query),
                ("Results", str(len(results))),
                ("Top Relevance", f"{results[0].relevance:.2f}" if results else "N/A"),
            ], emoji="🔍")

            return results

        except Exception as e:
            log.error_tree("RAG Retrieval Failed", e)
            return []

    def build_context(self, query: str, max_tokens: int = 2000) -> str:
        """
        Build context string for AI from retrieved results.

        Args:
            query: The user's question
            max_tokens: Approximate max length (in characters, ~4 chars per token)

        Returns:
            Formatted context string
        """
        results = self.retrieve(query, n_results=10)

        if not results:
            return ""

        sections = {
            "knowledge": [],
            "messages": [],
            "users": [],
        }

        for result in results:
            if result.source == self.KNOWLEDGE_COLLECTION:
                sections["knowledge"].append(result.content)
            elif result.source == self.MESSAGES_COLLECTION:
                author = result.metadata.get("author_name", "Unknown")
                channel = result.metadata.get("channel_name", "Unknown")
                sections["messages"].append(f"[#{channel}] {author}: {result.content}")
            elif result.source == self.USERS_COLLECTION:
                sections["users"].append(result.content)

        lines = []
        char_count = 0
        max_chars = max_tokens * 4

        # Add knowledge first (most important)
        if sections["knowledge"]:
            lines.append("=== RELEVANT SERVER KNOWLEDGE ===")
            for item in sections["knowledge"][:5]:
                if char_count + len(item) > max_chars:
                    break
                lines.append(item)
                char_count += len(item)
            lines.append("")

        # Add relevant messages
        if sections["messages"] and char_count < max_chars:
            lines.append("=== RELEVANT PAST CONVERSATIONS ===")
            for item in sections["messages"][:5]:
                if char_count + len(item) > max_chars:
                    break
                lines.append(item)
                char_count += len(item)
            lines.append("")

        # Add user info if relevant
        if sections["users"] and char_count < max_chars:
            lines.append("=== USER INFO ===")
            for item in sections["users"][:2]:
                if char_count + len(item) > max_chars:
                    break
                lines.append(item)
                char_count += len(item)

        return "\n".join(lines)

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    async def index_server_structure(self, guild) -> int:
        """Index server channels, roles, and basic structure."""
        if not self.is_available:
            return 0

        indexed = 0

        # Index channels
        for channel in guild.text_channels:
            desc = channel.topic or f"Text channel in {channel.category.name if channel.category else 'server'}"
            if self.add_channel_info(channel.name, desc):
                indexed += 1

        # Index roles
        for role in guild.roles:
            if role.name == "@everyone":
                continue
            perms = []
            if role.permissions.administrator:
                perms.append("admin")
            if role.permissions.manage_messages:
                perms.append("can moderate")
            if role.permissions.kick_members:
                perms.append("can kick")
            if role.permissions.ban_members:
                perms.append("can ban")

            desc = f"Server role with {len(role.members)} members"
            if perms:
                desc += f" ({', '.join(perms)})"

            if self.add_role_info(role.name, desc):
                indexed += 1

        log.tree("Server Structure Indexed", [
            ("Items", str(indexed)),
            ("Channels", str(len(guild.text_channels))),
            ("Roles", str(len(guild.roles) - 1)),
        ], emoji="📊")

        return indexed

    def clear_collection(self, collection_name: str) -> bool:
        """Clear all items from a collection."""
        if not self.is_available or collection_name not in self.collections:
            return False

        try:
            # Delete and recreate collection
            self.chroma_client.delete_collection(collection_name)
            self.collections[collection_name] = self.chroma_client.create_collection(
                name=collection_name
            )
            log.tree("Collection Cleared", [
                ("Collection", collection_name),
            ], emoji="🗑️")
            return True
        except Exception as e:
            log.error_tree("Clear Collection Failed", e)
            return False

    def get_stats(self) -> dict:
        """Get statistics about the RAG store."""
        if not self.is_available:
            return {}

        return {
            "knowledge_count": self.collections[self.KNOWLEDGE_COLLECTION].count(),
            "messages_count": self.collections[self.MESSAGES_COLLECTION].count(),
            "users_count": self.collections[self.USERS_COLLECTION].count(),
            "data_path": str(self.DATA_DIR),
        }


# Global instance
rag_service = RAGService()
