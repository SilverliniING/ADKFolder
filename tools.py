"""
MCP Tool Implementations

Pure functions that perform actual work: reading GCS, parsing documents,
writing to Firestore, and querying data.
"""

import io
import json
import logging
import os
import uuid
from typing import Any, Optional

from google.cloud import storage, firestore

logger = logging.getLogger("academic_agent_mcp")

# Initialize GCS & Firestore clients
gcs_client = storage.Client()
db_client = firestore.Client(
    project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    database="agentdatabase"
)


def read_gcs_document(bucket_name: str, blob_path: str) -> dict:
    """
    Read and parse a document from Google Cloud Storage bucket.
    Returns the document content and basic metadata.

    Args:
        bucket_name: The GCS bucket name (e.g. 'my-academic-documents')
        blob_path: The path to the document in the bucket (e.g. 'papers/2024/quantum.pdf')

    Returns:
        dict with keys: success, content, metadata, format (or error, status on failure)
    """
    try:
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        if not blob.exists():
            return {"error": f"Document not found: {blob_path}", "status": 404}

        blob.reload()
        metadata = {
            "name": blob.name,
            "size": blob.size,
            "content_type": blob.content_type,
            "created": blob.time_created.isoformat() if blob.time_created else None,
            "updated": blob.updated.isoformat() if blob.updated else None
        }

        # Handle PDF files
        if blob_path.endswith('.pdf'):
            try:
                import PyPDF2
                content_bytes = blob.download_as_bytes()
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(content_bytes))
                text_content = ""
                for page in pdf_reader.pages:
                    text_content += page.extract_text() or ""
                return {"success": True, "content": text_content, "metadata": metadata, "format": "pdf"}
            except ImportError:
                return {"error": "PyPDF2 not installed. Cannot parse PDF.", "status": 400}

        # Handle JSON files
        elif blob_path.endswith('.json'):
            content = blob.download_as_string().decode('utf-8')
            return {"success": True, "content": json.loads(content), "metadata": metadata, "format": "json"}

        # Handle text files (default)
        else:
            content = blob.download_as_string().decode('utf-8')
            return {"success": True, "content": content, "metadata": metadata, "format": "text"}

    except Exception as e:
        logger.error(f"Error reading GCS document: {e}")
        return {"error": str(e), "status": 500}


def extract_academic_metadata(document_content: str, extraction_format: str = "full") -> dict:
    """
    Extract structured academic metadata from document content.
    Handles multiple document formats and fallback strategies.

    Args:
        document_content: The document text content to parse
        extraction_format: What to extract
            - 'full': all metadata (title, authors, institution, date, topics, summary)
            - 'summary': title and authors only
            - 'references': extracted citations and references only

    Returns:
        dict with keys: success, data, format (or error, status on failure)
    """
    try:
        metadata = {
            "title": None,
            "authors": [],
            "institution": None,
            "date": None,
            "topics": [],
            "summary": None
        }

        lines = document_content.split('\n')

        # Extract metadata from first 100 lines (increased from 50)
        for line in lines[:100]:
            if not line.strip():
                continue

            line_lower = line.lower()

            # Extract title (more flexible matching)
            if not metadata["title"] and any(kw in line_lower for kw in ["title:", "paper:", "abstract:"]):
                metadata["title"] = line.split(":", 1)[1].strip() if ":" in line else line

            # Extract authors (more flexible)
            if not metadata["authors"] and any(kw in line_lower for kw in ["author", "by ", "authors:"]):
                if ":" in line:
                    authors_text = line.split(":", 1)[1].strip()
                    metadata["authors"] = [a.strip() for a in authors_text.split(",") if a.strip()]
                elif "by " in line_lower:
                    authors_text = line.split("by", 1)[1].strip()
                    metadata["authors"] = [a.strip() for a in authors_text.split(",") if a.strip()]

            # Extract institution (more flexible)
            if not metadata["institution"] and any(kw in line_lower for kw in ["affiliation:", "institution:", "university:", "from "]):
                if ":" in line:
                    metadata["institution"] = line.split(":", 1)[1].strip()
                elif "from " in line_lower:
                    metadata["institution"] = line.split("from", 1)[1].strip()

            # Extract date (more flexible)
            if not metadata["date"] and any(kw in line_lower for kw in ["date:", "published:", "year:", "in 20", "in 19"]):
                if ":" in line:
                    metadata["date"] = line.split(":", 1)[1].strip()
                else:
                    # Extract year if present
                    import re
                    year_match = re.search(r'(19|20)\d{2}', line)
                    if year_match:
                        metadata["date"] = year_match.group()

        # Extract summary (first substantive paragraph - improved)
        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) > 50:  # Lowered threshold from 100
                metadata["summary"] = stripped[:500]
                break

        # If no title found, use first non-empty line as title
        if not metadata["title"] and lines:
            for line in lines:
                if line.strip() and len(line.strip()) > 5:
                    metadata["title"] = line.strip()[:100]
                    break

        # If no summary found, use first paragraph after metadata
        if not metadata["summary"]:
            for line in lines:
                if line.strip() and len(line.strip()) > 50:
                    # Skip if it looks like metadata
                    if not any(kw in line.lower() for kw in ["title:", "author:", "date:", "abstract:"]):
                        metadata["summary"] = line.strip()[:500]
                        break

        # Filter response based on extraction_format
        if extraction_format == "summary":
            return {
                "success": True,
                "data": {
                    "title": metadata["title"],
                    "authors": metadata["authors"],
                    "format": extraction_format
                }
            }

        elif extraction_format == "references":
            references = [line for line in lines if line.strip() and any(
                kw in line.lower() for kw in ["[1]", "[2]", "doi:", "arxiv:", "reference"]
            )]
            return {
                "success": True,
                "data": {
                    "references": references[:10],
                    "format": extraction_format
                }
            }

        return {"success": True, "data": metadata, "format": extraction_format}

    except Exception as e:
        logger.error(f"Error extracting metadata: {e}")
        return {"error": str(e), "status": 500}


def write_to_firestore(collection: str, data: dict, document_id: str = "") -> dict:
    """
    Write extracted metadata and analysis results to Firestore database.

    Args:
        collection: Firestore collection name (e.g. 'academic_papers')
        data: The data object to store (any JSON-serializable structure)
        document_id: Document ID — leave empty for auto-generated UUID

    Returns:
        dict with keys: success, document_id, collection (or error, status on failure)
    """
    try:
        if not document_id:
            document_id = str(uuid.uuid4())

        # Create a copy of data to avoid modifying the original
        data_to_store = data.copy()

        # Add metadata with server timestamp
        data_to_store["_created_at"] = firestore.SERVER_TIMESTAMP
        data_to_store["_document_id"] = document_id

        # Write to Firestore
        db_client.collection(collection).document(document_id).set(data_to_store)

        logger.info(f"Written to Firestore: {collection}/{document_id}")

        # Return response without Sentinel objects (for JSON serialization)
        return {
            "success": True,
            "document_id": document_id,
            "collection": collection,
            "message": f"Successfully wrote to {collection}/{document_id}"
        }

    except Exception as e:
        logger.error(f"Error writing to Firestore: {e}")
        return {"error": str(e), "status": 500}


def list_gcs_documents(bucket_name: str, prefix: str = "") -> dict:
    """
    List all documents in a GCS bucket, optionally filtered by prefix.

    Args:
        bucket_name: The GCS bucket name
        prefix: Optional prefix to filter results (e.g. 'papers/2024/')

    Returns:
        dict with keys: success, bucket, prefix, documents, count (or error, status on failure)
    """
    try:
        bucket = gcs_client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix if prefix else None)

        documents = [
            {
                "name": blob.name,
                "size": blob.size,
                "content_type": blob.content_type,
                "updated": blob.updated.isoformat() if blob.updated else None
            }
            for blob in blobs
        ]

        return {
            "success": True,
            "bucket": bucket_name,
            "prefix": prefix,
            "documents": documents,
            "count": len(documents)
        }

    except Exception as e:
        logger.error(f"Error listing GCS documents: {e}")
        return {"error": str(e), "status": 500}


def query_firestore(collection: str, filter_field: str = "", filter_value: str = "", limit: int = 10) -> dict:
    """
    Query documents from Firestore collection with optional filtering.

    Args:
        collection: Collection name to query
        filter_field: Field name to filter on (optional)
        filter_value: Value to match (optional)
        limit: Max documents to return (default: 10)

    Returns:
        dict with keys: success, collection, documents, count (or error, status on failure)
    """
    try:
        query = db_client.collection(collection)

        if filter_field and filter_value:
            query = query.where(filter_field, "==", filter_value)

        docs = query.limit(limit).stream()

        # Convert documents to JSON-serializable format
        results = []
        for doc in docs:
            doc_data = doc.to_dict()
            # Remove Sentinel objects that can't be serialized
            if doc_data:
                # Convert special Firestore types to strings
                for key in list(doc_data.keys()):
                    if key.startswith("_"):
                        # Skip internal fields that might contain Sentinels
                        continue
                    value = doc_data[key]
                    # Check if value is a Sentinel-like object
                    if hasattr(value, '__class__') and 'Sentinel' in value.__class__.__name__:
                        doc_data[key] = str(value)

            results.append({"id": doc.id, "data": doc_data})

        return {
            "success": True,
            "collection": collection,
            "documents": results,
            "count": len(results)
        }

    except Exception as e:
        logger.error(f"Error querying Firestore: {e}")
        return {"error": str(e), "status": 500}
