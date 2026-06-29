"""
Invoice Matching Tools

Pure functions that perform actual work: reading financial documents from GCS,
parsing invoices and bank statements, matching records, and managing Firestore entries.
"""

import io
import json
import logging
import os
import uuid
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional
import re
from difflib import SequenceMatcher

from google.cloud import storage, firestore

logger = logging.getLogger("invoice_matching_agent")

# Initialize GCS & Firestore clients
gcs_client = storage.Client()
db_client = firestore.Client(
    project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    database=os.environ.get("FIRESTORE_DB", "(default)")
)

INVOICES_BUCKET = os.environ.get("INVOICES_BUCKET", "invoices26-123")
PAYMENTS_BUCKET = os.environ.get("PAYMENTS_BUCKET", "payments26-123")
MATCH_DATE_TOLERANCE_DAYS = 7
VENDOR_MATCH_THRESHOLD = 0.75  # Fuzzy match score (0-1)


def read_gcs_document(bucket_name: str, blob_path: str) -> dict:
    """
    Read and parse a document from Google Cloud Storage bucket.
    Returns the document content and basic metadata.

    Args:
        bucket_name: The GCS bucket name (e.g. 'invoices-bucket')
        blob_path: The path to the document in the bucket (e.g. '2026/invoice-001.pdf')

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

        # Handle CSV/text files (default)
        else:
            content = blob.download_as_string().decode('utf-8')
            return {"success": True, "content": content, "metadata": metadata, "format": "text"}

    except Exception as e:
        logger.error(f"Error reading GCS document: {e}")
        return {"error": str(e), "status": 500}


def list_gcs_documents(bucket_name: str, prefix: str = "") -> dict:
    """
    List all documents in a GCS bucket, optionally filtered by prefix.

    Args:
        bucket_name: The GCS bucket name (e.g. 'invoices-bucket')
        prefix: Optional prefix to filter results (e.g. '2026/')

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


def parse_financial_document(document_content: str, doc_type: str = "invoice") -> dict:
    """
    Extract structured financial data from document content using LLM.
    Uses Gemini to intelligently parse financial documents.

    Args:
        document_content: The document text content to parse
        doc_type: Either "invoice" or "payment" — determines what fields to extract

    Returns:
        dict with keys: success, vendor, amount, currency, date, reference_id, description
        (or error, status on failure)
    """
    try:
        import re
        from google import genai

        # Create extraction prompt
        if doc_type == "payment":
            prompt = """Extract financial data from this bank statement:
1. Vendor/Payee name
2. Payment amount (numeric only)
3. Currency code (USD, EUR, etc.)
4. Payment date (YYYY-MM-DD)
5. Transaction ID or reference number
6. Brief description

Return ONLY a JSON object with keys: vendor, amount, currency, date, reference_id, description
Set missing fields to null. Amount must be numeric."""
        else:
            prompt = """Extract financial data from this invoice:
1. Vendor/Supplier name
2. Invoice amount (numeric only)
3. Currency code (USD, EUR, etc.)
4. Invoice date (YYYY-MM-DD)
5. Invoice number or reference
6. Brief description of items

Return ONLY a JSON object with keys: vendor, amount, currency, date, reference_id, description
Set missing fields to null. Amount must be numeric."""

        prompt += f"\n\nDocument:\n{document_content[:2000]}"

        # Call Gemini to extract fields
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        # Parse the JSON response
        response_text = response.text.strip()

        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text

        extracted = json.loads(json_str)

        # Validate required fields
        if not extracted.get("vendor") or extracted.get("amount") is None:
            return {"error": "Could not extract required fields (vendor, amount)", "status": 400}

        # Convert amount to float if it's a string
        try:
            amount = float(extracted.get("amount", 0))
        except (ValueError, TypeError):
            return {"error": "Invalid amount format", "status": 400}

        return {
            "success": True,
            "vendor": str(extracted.get("vendor", "")).strip(),
            "amount": amount,
            "currency": str(extracted.get("currency", "USD")).upper(),
            "date": str(extracted.get("date") or ""),
            "reference_id": str(extracted.get("reference_id") or ""),
            "description": str(extracted.get("description") or "")[:500]
        }

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {e}")
        return {"error": f"Failed to parse LLM response: {str(e)}", "status": 400}
    except Exception as e:
        logger.error(f"Error parsing financial document: {e}")
        return {"error": str(e), "status": 500}


def write_firestore_record(collection: str, data: dict, document_id: str = "") -> dict:
    """
    Write a financial record (invoice or bankstatement) to Firestore.

    Args:
        collection: Either "invoices" or "payments"
        data: The parsed financial data (vendor, amount, date, etc.)
        document_id: Optional document ID; auto-generated if empty

    Returns:
        dict with keys: success, document_id, collection (or error, status on failure)
    """
    try:
        if collection not in ["invoices", "payments"]:
            return {"error": f"Invalid collection: {collection}", "status": 400}

        if not document_id:
            document_id = str(uuid.uuid4())

        # Prepare data for storage
        data_to_store = data.copy()
        data_to_store["_created_at"] = firestore.SERVER_TIMESTAMP
        data_to_store["_document_id"] = document_id
        data_to_store["matched_invoice_id"] = None if collection == "payments" else None
        data_to_store["matched_payment_id"] = None if collection == "invoices" else None

        # Write to Firestore
        db_client.collection(collection).document(document_id).set(data_to_store)

        logger.info(f"Written to Firestore: {collection}/{document_id}")

        return {
            "success": True,
            "document_id": document_id,
            "collection": collection,
            "message": f"Successfully wrote to {collection}/{document_id}"
        }

    except Exception as e:
        logger.error(f"Error writing to Firestore: {e}")
        return {"error": str(e), "status": 500}

def normalize_vendor_name(vendor: str) -> str:
    """
    Normalize vendor names for fuzzy matching.

    Examples:
        Microsoft Corporation -> microsoft
        Microsoft Corp        -> microsoft
        Umbrella Ltd          -> umbrella
        Umbrella Limited      -> umbrella
        Globex Corporation    -> globex
        ACME Technologies Inc. -> acme technologies
    """
    if not vendor or not isinstance(vendor, str):
        return ""

    vendor = vendor.lower().strip()

    # Remove punctuation
    vendor = re.sub(r"[^\w\s]", " ", vendor)

    # Remove common company suffixes
    suffixes = {
        "inc", "incorporated",
        "corp", "corporation",
        "co", "company",
        "ltd", "limited",
        "llc", "plc",
        "pte", "private"
    }

    words = [word for word in vendor.split() if word not in suffixes]

    return " ".join(words).strip()


def fuzzy_match_vendors(vendor1: str, vendor2: str) -> float:
    """
    Return a similarity score between 0 and 1.

    Gives high scores for:
        Microsoft Corporation <-> Microsoft Corp
        Umbrella Ltd          <-> Umbrella Limited
        Globex Corporation    <-> Globex Corp
    """

    if not vendor1 or not vendor2:
        return 0.0

    v1 = normalize_vendor_name(vendor1)
    v2 = normalize_vendor_name(vendor2)

    if not v1 or not v2:
        return 0.0

    # Exact normalized match
    if v1 == v2:
        return 1.0

    # Partial match (e.g. "amazon" vs "amazon web services")
    if v1 in v2 or v2 in v1:
        return 0.95

    # Fuzzy similarity
    return SequenceMatcher(None, v1, v2).ratio()

def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string in multiple formats."""
    if not date_str:
        return None

    formats = ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def match_documents() -> dict:
    """
    Cross-reference all invoices and payments, matching by vendor and amount.
    Updates matched_*_id fields in both collections.
    Gracefully skips documents with errors and reports them as unmatched.

    Returns:
        dict with keys: success, matched_count, matched_pairs, unmatched_invoices, unmatched_payments, error_invoices, error_payments
    """
    try:
        # Fetch all invoices and payments
        invoices = list(db_client.collection("invoices").stream())
        payments = list(db_client.collection("payments").stream())

        matched_count = 0
        matched_pairs = []
        unmatched_invoices = []
        unmatched_payments = set(p.id for p in payments)
        error_invoices = []
        error_payments = []

        # First pass: validate all invoices and payments, skip those with errors
        valid_invoices = []
        for invoice in invoices:
            try:
                inv_data = invoice.to_dict()
                inv_vendor = inv_data.get("vendor")
                inv_amount = inv_data.get("amount")

                # Validate vendor is a non-empty string
                if inv_vendor is None or not isinstance(inv_vendor, str) or inv_vendor.strip() == "":
                    error_invoices.append({
                        "id": invoice.id,
                        "vendor": inv_vendor,
                        "amount": inv_amount,
                        "date": inv_data.get("date"),
                        "error": f"Invalid vendor: {repr(inv_vendor)} (must be non-empty string)",
                        "gcs_link": inv_data.get("gcs_link")
                    })
                    logger.warning(f"Skipping invoice {invoice.id}: invalid vendor {repr(inv_vendor)}")
                    continue

                # Validate amount exists and is numeric
                if inv_amount is None:
                    error_invoices.append({
                        "id": invoice.id,
                        "vendor": inv_vendor,
                        "amount": inv_amount,
                        "date": inv_data.get("date"),
                        "error": "Missing required field: amount",
                        "gcs_link": inv_data.get("gcs_link")
                    })
                    logger.warning(f"Skipping invoice {invoice.id}: missing amount")
                    continue

                try:
                    _ = float(inv_amount)
                except (ValueError, TypeError):
                    error_invoices.append({
                        "id": invoice.id,
                        "vendor": inv_vendor,
                        "amount": inv_amount,
                        "date": inv_data.get("date"),
                        "error": f"Invalid amount: cannot convert {repr(inv_amount)} to float",
                        "gcs_link": inv_data.get("gcs_link")
                    })
                    logger.warning(f"Skipping invoice {invoice.id}: invalid amount {repr(inv_amount)}")
                    continue

                valid_invoices.append((invoice, inv_data))
            except Exception as e:
                logger.error(f"Error validating invoice {invoice.id}: {e}")
                error_invoices.append({
                    "id": invoice.id,
                    "error": f"Exception during validation: {str(e)}"
                })

        valid_payments = []
        for payment in payments:
            try:
                pay_data = payment.to_dict()
                pay_vendor = pay_data.get("vendor")
                pay_amount = pay_data.get("amount")

                # Validate vendor is a non-empty string
                if pay_vendor is None or not isinstance(pay_vendor, str) or pay_vendor.strip() == "":
                    error_payments.append({
                        "id": payment.id,
                        "vendor": pay_vendor,
                        "amount": pay_amount,
                        "date": pay_data.get("date"),
                        "error": f"Invalid vendor: {repr(pay_vendor)} (must be non-empty string)",
                        "gcs_link": pay_data.get("gcs_link")
                    })
                    logger.warning(f"Skipping payment {payment.id}: invalid vendor {repr(pay_vendor)}")
                    continue

                # Validate amount exists and is numeric
                if pay_amount is None:
                    error_payments.append({
                        "id": payment.id,
                        "vendor": pay_vendor,
                        "amount": pay_amount,
                        "date": pay_data.get("date"),
                        "error": "Missing required field: amount",
                        "gcs_link": pay_data.get("gcs_link")
                    })
                    logger.warning(f"Skipping payment {payment.id}: missing amount")
                    continue

                try:
                    _ = float(pay_amount)
                except (ValueError, TypeError):
                    error_payments.append({
                        "id": payment.id,
                        "vendor": pay_vendor,
                        "amount": pay_amount,
                        "date": pay_data.get("date"),
                        "error": f"Invalid amount: cannot convert {repr(pay_amount)} to float",
                        "gcs_link": pay_data.get("gcs_link")
                    })
                    logger.warning(f"Skipping payment {payment.id}: invalid amount {repr(pay_amount)}")
                    continue

                valid_payments.append((payment, pay_data))
            except Exception as e:
                logger.error(f"Error validating payment {payment.id}: {e}")
                error_payments.append({
                    "id": payment.id,
                    "error": f"Exception during validation: {str(e)}"
                })

        # Second pass: match valid documents only
        valid_payment_ids = set(p[0].id for p in valid_payments)
        unmatched_payments = valid_payment_ids.copy()

        for invoice, inv_data in valid_invoices:
            try:
                inv_vendor = inv_data.get("vendor")
                inv_amount = inv_data.get("amount")
                inv_date = parse_date(inv_data.get("date"))
                best_match = None
                best_score = 0

                # Find best matching payment
                for payment, pay_data in valid_payments:
                    try:
                        pay_vendor = pay_data.get("vendor")
                        pay_amount = pay_data.get("amount")
                        pay_date = parse_date(pay_data.get("date"))

                        # Check amount match (exact)
                        if inv_amount != pay_amount:
                            continue

                        # Check vendor match (fuzzy)
                        vendor_score = fuzzy_match_vendors(inv_vendor, pay_vendor)
                        if vendor_score < VENDOR_MATCH_THRESHOLD:
                            continue

                        # Check date match (within tolerance)
                        if inv_date and pay_date:
                            date_diff = abs((pay_date - inv_date).days)
                            if date_diff > MATCH_DATE_TOLERANCE_DAYS:
                                continue

                        # This is a valid match
                        if vendor_score > best_score:
                            best_match = payment.id
                            best_score = vendor_score

                    except Exception as e:
                        logger.error(f"Error matching invoice {invoice.id} with payment {payment.id}: {e}")
                        continue

                # Update invoice record
                if best_match:
                    db_client.collection("invoices").document(invoice.id).update({
                        "matched_payment_id": best_match
                    })
                    # Update payment record
                    db_client.collection("payments").document(best_match).update({
                        "matched_invoice_id": invoice.id
                    })
                    matched_count += 1
                    matched_pairs.append({
                        "invoice_id": invoice.id,
                        "payment_id": best_match,
                        "vendor": inv_vendor,
                        "amount": inv_amount
                    })
                    # Remove from unmatched set
                    if best_match in unmatched_payments:
                        unmatched_payments.remove(best_match)
                else:
                    unmatched_invoices.append({
                        "id": invoice.id,
                        "vendor": inv_vendor,
                        "amount": inv_amount,
                        "date": inv_data.get("date"),
                        "gcs_link": inv_data.get("gcs_link")
                    })

            except Exception as e:
                logger.error(f"Error processing invoice {invoice.id}: {e}")
                error_invoices.append({
                    "id": invoice.id,
                    "vendor": inv_data.get("vendor"),
                    "amount": inv_data.get("amount"),
                    "date": inv_data.get("date"),
                    "error": f"Exception during matching: {str(e)}",
                    "gcs_link": inv_data.get("gcs_link")
                })

        # Collect unmatched payments
        unmatched_payments_list = []
        for payment, pay_data in valid_payments:
            if payment.id in unmatched_payments:
                unmatched_payments_list.append({
                    "id": payment.id,
                    "vendor": pay_data.get("vendor"),
                    "amount": pay_data.get("amount"),
                    "date": pay_data.get("date"),
                    "gcs_link": pay_data.get("gcs_link")
                })

        result = {
            "success": True,
            "matched_count": matched_count,
            "matched_pairs": matched_pairs,
            "unmatched_invoices": unmatched_invoices,
            "unmatched_payments": unmatched_payments_list
        }

        # Add error lists only if there are errors
        if error_invoices:
            result["error_invoices"] = error_invoices
            logger.warning(f"Skipped {len(error_invoices)} invoices due to errors")
        if error_payments:
            result["error_payments"] = error_payments
            logger.warning(f"Skipped {len(error_payments)} payments due to errors")

        return result

    except Exception as e:
        logger.error(f"Critical error in match_documents: {e}")
        return {"error": str(e), "status": 500}


def query_firestore_matches(collection: str = "invoices", filter_matched: Optional[bool] = None) -> dict:
    """
    Query documents from Firestore with optional filtering by match status.

    Args:
        collection: Either "invoices" or "payments"
        filter_matched: None=all, True=matched only, False=unmatched only

    Returns:
        dict with keys: success, collection, documents, count
    """
    try:
        query = db_client.collection(collection)

        if filter_matched is True:
            match_field = "matched_payment_id" if collection == "invoices" else "matched_invoice_id"
            query = query.where(match_field, "!=", None)
        elif filter_matched is False:
            match_field = "matched_payment_id" if collection == "invoices" else "matched_invoice_id"
            query = query.where(match_field, "==", None)

        docs = query.limit(1000).stream()

        results = []
        for doc in docs:
            doc_data = doc.to_dict()
            # Skip internal fields
            cleaned_data = {k: v for k, v in doc_data.items() if not k.startswith("_")}
            results.append({"id": doc.id, "data": cleaned_data})

        return {
            "success": True,
            "collection": collection,
            "documents": results,
            "count": len(results)
        }

    except Exception as e:
        logger.error(f"Error querying Firestore: {e}")
        return {"error": str(e), "status": 500}


def generate_reconciliation_report(error_invoices: Optional[list] = None, error_payments: Optional[list] = None) -> dict:
    """
    Generate a formatted reconciliation report with matched pairs and unmatched records.

    Args:
        error_invoices: Optional list of invoices with errors (from match_documents)
        error_payments: Optional list of payments with errors (from match_documents)

    Returns:
        dict with keys: success, matched_table, unmatched_invoices, unmatched_payments, error_invoices, error_payments, summary
    """
    try:
        # Get all matched pairs
        invoices = query_firestore_matches("invoices")["documents"]
        payments = query_firestore_matches("payments")["documents"]

        matched_table = []
        unmatched_inv = []
        unmatched_pay = []

        # Build matched pairs table
        for inv in invoices:
            inv_data = inv["data"]
            if inv_data.get("matched_payment_id"):
                # Find the corresponding payment
                payment = next(
                    (p for p in payments if p["id"] == inv_data.get("matched_payment_id")),
                    None
                )
                if payment:
                    matched_table.append({
                        "invoice_id": inv["id"],
                        "invoice_number": inv_data.get("reference_id", "N/A"),
                        "vendor": inv_data.get("vendor", "Unknown"),
                        "amount": inv_data.get("amount", 0),
                        "invoice_date": inv_data.get("date", "N/A"),
                        "payment_id": payment["id"],
                        "payment_date": payment["data"].get("date", "N/A"),
                        "status": "✓ Matched"
                    })
            else:
                unmatched_inv.append({
                    "invoice_id": inv["id"],
                    "invoice_number": inv_data.get("reference_id", "N/A"),
                    "vendor": inv_data.get("vendor", "Unknown"),
                    "amount": inv_data.get("amount", 0),
                    "date": inv_data.get("date", "N/A")
                })

        # Find unmatched payments
        for pay in payments:
            if not pay["data"].get("matched_invoice_id"):
                unmatched_pay.append({
                    "payment_id": pay["id"],
                    "transaction_id": pay["data"].get("reference_id", "N/A"),
                    "vendor": pay["data"].get("vendor", "Unknown"),
                    "amount": pay["data"].get("amount", 0),
                    "date": pay["data"].get("date", "N/A")
                })

        summary = {
            "total_invoices": len(invoices),
            "total_payments": len(payments),
            "matched_pairs": len(matched_table),
            "unmatched_invoices": len(unmatched_inv),
            "unmatched_payments": len(unmatched_pay),
            "error_invoices": len(error_invoices) if error_invoices else 0,
            "error_payments": len(error_payments) if error_payments else 0,
            "match_rate": f"{len(matched_table) / len(invoices) * 100:.1f}%" if invoices else "0%"
        }

        result = {
            "success": True,
            "matched_table": matched_table,
            "unmatched_invoices": unmatched_inv,
            "unmatched_payments": unmatched_pay,
            "summary": summary
        }

        if error_invoices:
            result["error_invoices"] = error_invoices
        if error_payments:
            result["error_payments"] = error_payments

        return result

    except Exception as e:
        logger.error(f"Error generating reconciliation report: {e}")
        return {"error": str(e), "status": 500}


def format_report_as_text(report: dict) -> str:
    """
    Format reconciliation report as human-readable text output.

    Args:
        report: Output from generate_reconciliation_report()

    Returns:
        Formatted text string with tables and summaries
    """
    if not report.get("success"):
        return f"Error: {report.get('error', 'Unknown error')}"

    output = []
    output.append("=" * 80)
    output.append("INVOICE RECONCILIATION REPORT")
    output.append("=" * 80)
    output.append("")

    # Summary
    summary = report["summary"]
    output.append("SUMMARY")
    output.append("-" * 80)
    output.append(f"Total Invoices:        {summary['total_invoices']}")
    output.append(f"Total Payments:        {summary['total_payments']}")
    output.append(f"Matched Pairs:         {summary['matched_pairs']}")
    output.append(f"Unmatched Invoices:    {summary['unmatched_invoices']}")
    output.append(f"Unmatched Payments:    {summary['unmatched_payments']}")
    if summary.get("error_invoices", 0) > 0:
        output.append(f"Error Invoices:        {summary['error_invoices']} (skipped due to data issues)")
    if summary.get("error_payments", 0) > 0:
        output.append(f"Error Payments:        {summary['error_payments']} (skipped due to data issues)")
    output.append(f"Match Rate:            {summary['match_rate']}")
    output.append("")

    # Matched pairs table
    if report["matched_table"]:
        output.append("MATCHED PAIRS")
        output.append("-" * 80)
        output.append(
            f"{'Invoice #':<20} {'Vendor':<20} {'Amount':<12} {'Payment Date':<15} {'Status':<10}"
        )
        output.append("-" * 80)
        for match in report["matched_table"]:
            output.append(
                f"{match['invoice_number']:<20} "
                f"{match['vendor']:<20} "
                f"${match['amount']:<11.2f} "
                f"{match['payment_date']:<15} "
                f"{match['status']:<10}"
            )
        output.append("")

    # Unmatched invoices
    if report["unmatched_invoices"]:
        output.append("UNMATCHED INVOICES")
        output.append("-" * 80)
        for inv in report["unmatched_invoices"]:
            output.append(
                f"  {inv['invoice_number']}: {inv['vendor']} - "
                f"${inv['amount']:.2f} ({inv['date']})"
            )
        output.append("")

    # Unmatched payments
    if report["unmatched_payments"]:
        output.append("UNMATCHED PAYMENTS")
        output.append("-" * 80)
        for pay in report["unmatched_payments"]:
            output.append(
                f"  {pay['transaction_id']}: {pay['vendor']} - "
                f"${pay['amount']:.2f} ({pay['date']})"
            )
        output.append("")

    # Error invoices (skipped due to data issues)
    if report.get("error_invoices"):
        output.append("ERROR INVOICES (Skipped - Data Issues)")
        output.append("-" * 80)
        for inv in report["error_invoices"]:
            error_msg = inv.get("error", "Unknown error")
            gcs_link = inv.get("gcs_link", "N/A")
            output.append(
                f"  ID: {inv['id']}"
            )
            output.append(
                f"    Vendor: {inv.get('vendor', 'N/A')} | Amount: {inv.get('amount', 'N/A')} | Date: {inv.get('date', 'N/A')}"
            )
            output.append(
                f"    Error: {error_msg}"
            )
            if gcs_link != "N/A":
                output.append(
                    f"    Source: {gcs_link}"
                )
        output.append("")

    # Error payments (skipped due to data issues)
    if report.get("error_payments"):
        output.append("ERROR PAYMENTS (Skipped - Data Issues)")
        output.append("-" * 80)
        for pay in report["error_payments"]:
            error_msg = pay.get("error", "Unknown error")
            gcs_link = pay.get("gcs_link", "N/A")
            output.append(
                f"  ID: {pay['id']}"
            )
            output.append(
                f"    Vendor: {pay.get('vendor', 'N/A')} | Amount: {pay.get('amount', 'N/A')} | Date: {pay.get('date', 'N/A')}"
            )
            output.append(
                f"    Error: {error_msg}"
            )
            if gcs_link != "N/A":
                output.append(
                    f"    Source: {gcs_link}"
                )
        output.append("")

    output.append("=" * 80)
    return "\n".join(output)
