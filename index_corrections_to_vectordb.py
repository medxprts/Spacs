#!/usr/bin/env python3
"""
Index Corrections to Vector Database

One-time script to index your 369 corrections into ChromaDB for RAG retrieval.
Creates semantic search over all past corrections.
"""

import os
import sys
from typing import List, Dict
from datetime import datetime

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal
from sqlalchemy import text
import chromadb
from chromadb.utils import embedding_functions
import json

# Use sentence-transformers for embeddings (free, local)
# Alternative: OpenAI embeddings (costs ~$0.04 for 369 corrections)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, good quality, free


class CorrectionIndexer:
    """Index corrections into vector database for semantic search"""

    def __init__(self, db_path: str = "./correction_vector_db"):
        """
        Initialize ChromaDB client.

        Args:
            db_path: Path to store vector database (persistent)
        """
        print(f"🔧 Initializing ChromaDB at {db_path}...")

        # Create persistent client
        self.client = chromadb.PersistentClient(path=db_path)

        # Use sentence-transformers for embeddings (free, local)
        self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )

        # Create or get collection
        self.collection = self.client.get_or_create_collection(
            name="spac_corrections",
            embedding_function=self.embedding_function,
            metadata={"description": "SPAC data quality corrections for self-learning"}
        )

        print(f"✅ ChromaDB initialized")
        print(f"   Collection: {self.collection.name}")
        print(f"   Existing documents: {self.collection.count()}")

    def load_corrections_from_db(self) -> List[Dict]:
        """Load corrections from PostgreSQL database"""
        print("\n📊 Loading corrections from database...")

        db = SessionLocal()

        try:
            query = """
                SELECT
                    id,
                    ticker,
                    issue_type,
                    original_data,
                    proposed_fix,
                    final_fix,
                    learning_notes,
                    created_at
                FROM data_quality_conversations
                WHERE
                    learning_notes IS NOT NULL
                    AND final_fix IS NOT NULL
                ORDER BY created_at DESC
            """

            result = db.execute(text(query))
            rows = result.fetchall()

            corrections = []
            for row in rows:
                corrections.append({
                    'id': row[0],
                    'ticker': row[1],
                    'issue_type': row[2],
                    'original_data': row[3],
                    'proposed_fix': row[4],
                    'final_fix': row[5],
                    'learning_notes': row[6],
                    'created_at': row[7].isoformat() if row[7] else None
                })

            print(f"✅ Loaded {len(corrections)} corrections")
            return corrections

        finally:
            db.close()

    def format_correction_for_embedding(self, correction: Dict) -> str:
        """
        Format correction into text for embedding.

        This text will be used to create vector embedding for semantic search.
        Include all relevant context for similarity matching.
        """
        # Extract fields from final_fix
        fields_corrected = list(correction['final_fix'].keys()) if correction['final_fix'] else []

        # Build descriptive text
        text_parts = [
            f"Ticker: {correction['ticker']}",
            f"Issue Type: {correction['issue_type']}",
            f"Fields Corrected: {', '.join(fields_corrected)}",
            f"Learning Note: {correction['learning_notes']}",
        ]

        # Add field values
        if correction['final_fix']:
            for field, value in correction['final_fix'].items():
                text_parts.append(f"{field}: {value}")

        return "\n".join(text_parts)

    def index_corrections(self, corrections: List[Dict], batch_size: int = 100):
        """
        Index corrections into vector database.

        Args:
            corrections: List of correction dicts
            batch_size: Number of corrections to index per batch
        """
        print(f"\n🔍 Indexing {len(corrections)} corrections...")
        print(f"   Using embedding model: {EMBEDDING_MODEL}")
        print(f"   This may take 1-2 minutes...")

        # Clear existing collection (fresh start)
        current_count = self.collection.count()
        if current_count > 0:
            print(f"   ⚠️  Clearing {current_count} existing documents")
            # Delete collection and recreate
            self.client.delete_collection(name="spac_corrections")
            self.collection = self.client.create_collection(
                name="spac_corrections",
                embedding_function=self.embedding_function,
                metadata={"description": "SPAC data quality corrections for self-learning"}
            )

        # Prepare batches
        for i in range(0, len(corrections), batch_size):
            batch = corrections[i:i+batch_size]

            # Format for ChromaDB
            documents = []
            metadatas = []
            ids = []

            for correction in batch:
                # Document text (for embedding)
                doc_text = self.format_correction_for_embedding(correction)
                documents.append(doc_text)

                # Metadata (for filtering)
                metadatas.append({
                    'ticker': correction['ticker'],
                    'issue_type': correction['issue_type'],
                    'fields_corrected': json.dumps(list(correction['final_fix'].keys())) if correction['final_fix'] else '[]',
                    'created_at': correction['created_at'] or ''
                })

                # Unique ID
                ids.append(f"correction_{correction['id']}")

            # Add to ChromaDB (automatically generates embeddings)
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )

            print(f"   ✓ Indexed batch {i//batch_size + 1}/{(len(corrections) + batch_size - 1)//batch_size}")

        print(f"\n✅ Indexing complete!")
        print(f"   Total documents: {self.collection.count()}")

    def test_search(self, query: str, n_results: int = 3):
        """
        Test semantic search.

        Args:
            query: Search query
            n_results: Number of results to return
        """
        print(f"\n🔍 Testing search: '{query}'")

        results = self.collection.query(
            query_texts=[query],
            n_results=n_results
        )

        print(f"\n📋 Top {n_results} similar corrections:")
        for i, (doc, metadata, distance) in enumerate(zip(
            results['documents'][0],
            results['metadatas'][0],
            results['distances'][0]
        ), 1):
            print(f"\n   {i}. Similarity: {1 - distance:.2%}")
            print(f"      Ticker: {metadata['ticker']}")
            print(f"      Issue: {metadata['issue_type']}")
            print(f"      Preview: {doc[:150]}...")

    def get_stats(self):
        """Print statistics about indexed corrections"""
        total = self.collection.count()

        print(f"\n📊 Vector Database Stats:")
        print(f"   Total corrections indexed: {total}")
        print(f"   Embedding model: {EMBEDDING_MODEL}")
        print(f"   Embedding dimension: 384")  # all-MiniLM-L6-v2
        print(f"   Storage: ./correction_vector_db/")


def main():
    """Main indexing script"""
    import argparse

    parser = argparse.ArgumentParser(description='Index corrections to vector database')
    parser.add_argument('--test-query', type=str,
                        help='Test search with query after indexing')
    parser.add_argument('--stats-only', action='store_true',
                        help='Just show stats, don\'t re-index')

    args = parser.parse_args()

    # Initialize
    indexer = CorrectionIndexer()

    if args.stats_only:
        indexer.get_stats()
        return

    # Load corrections
    corrections = indexer.load_corrections_from_db()

    if not corrections:
        print("❌ No corrections found in database")
        return

    # Index
    indexer.index_corrections(corrections)

    # Stats
    indexer.get_stats()

    # Test search
    if args.test_query:
        indexer.test_search(args.test_query)
    else:
        # Default test queries
        print("\n" + "="*60)
        print("TESTING SEMANTIC SEARCH")
        print("="*60)

        indexer.test_search("Extract trust_value from SPAC filing", n_results=3)
        indexer.test_search("Missing data should return None", n_results=3)
        indexer.test_search("Deal announcement date", n_results=3)

    print("\n✅ Indexing complete! Vector database ready for RAG.")
    print("\n💡 Next step: Use RAG in your agents")
    print("   from agents.rag_learning_mixin import RAGLearningMixin")


if __name__ == '__main__':
    main()
