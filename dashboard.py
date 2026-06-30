import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime

st.set_page_config(
    page_title="Invoice Reconciliation Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📊 Invoice Reconciliation Dashboard")

# Sidebar configuration
with st.sidebar:
    st.header("Configuration")
    base_url = st.text_input(
        "API Base URL",
        value="http://localhost:8080",
        help="The base URL of your invoice matching service"
    )

    st.markdown("---")
    st.markdown("""
    ### How to use:
    1. Ensure your invoice matching service is running
    2. Click the **Analyze data** button below
    3. View matched pairs, unmatched records, and error summaries
    """)

# Main content
st.markdown("### Click below to run the reconciliation analysis")

if st.button("🔍 Analyze data", key="analyze_btn", use_container_width=True):
    with st.spinner("Running reconciliation analysis..."):
        try:
            # Make API request
            response = requests.post(
                f"{base_url}/match_invoices",
                json={
                    "jsonrpc": "2.0",
                    "id": "streamlit-dashboard",
                    "params": {
                        "message": {
                            "parts": [{
                                "type": "text",
                                "text": "Generate the final reconciliation report. Use generate_reconciliation_report and format_report_as_text to create a table showing: (1) All matched invoice-payment pairs with vendor names, amounts, and dates, (2) Summary statistics including total invoices, total payments, number of matches, and match rate, (3) List of unmatched invoices, (4) List of unmatched payments"
                            }]
                        }
                    }
                },
                timeout=120,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code != 200:
                st.error(f"API Error: {response.status_code}")
                st.error(response.text)
            else:
                data = response.json()

                # Extract agent response
                if "result" in data and "parts" in data["result"]:
                    report_text = data["result"]["parts"][0].get("text", "")

                    # Parse the report text to extract structured data
                    st.success("✅ Analysis completed successfully!")

                    # Display the raw report
                    with st.expander("📋 Full Report Text", expanded=True):
                        st.text(report_text)

                    # Try to parse and display structured data
                    st.markdown("---")

                    # Extract summary section
                    if "SUMMARY" in report_text:
                        st.subheader("📈 Summary Statistics")

                        lines = report_text.split("\n")
                        summary_data = {}

                        for i, line in enumerate(lines):
                            if "Total Invoices:" in line:
                                summary_data["Total Invoices"] = line.split(":")[-1].strip()
                            elif "Total Payments:" in line:
                                summary_data["Total Payments"] = line.split(":")[-1].strip()
                            elif "Matched Pairs:" in line:
                                summary_data["Matched Pairs"] = line.split(":")[-1].strip()
                            elif "Unmatched Invoices:" in line:
                                summary_data["Unmatched Invoices"] = line.split(":")[-1].strip()
                            elif "Unmatched Payments:" in line:
                                summary_data["Unmatched Payments"] = line.split(":")[-1].strip()
                            elif "Match Rate:" in line:
                                summary_data["Match Rate"] = line.split(":")[-1].strip()

                        # Display as metrics
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("Total Invoices", summary_data.get("Total Invoices", "N/A"))
                        with col2:
                            st.metric("Total Payments", summary_data.get("Total Payments", "N/A"))
                        with col3:
                            st.metric("Matched Pairs", summary_data.get("Matched Pairs", "N/A"))
                        with col4:
                            st.metric("Match Rate", summary_data.get("Match Rate", "N/A"))

                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Unmatched Invoices", summary_data.get("Unmatched Invoices", "N/A"))
                        with col2:
                            st.metric("Unmatched Payments", summary_data.get("Unmatched Payments", "N/A"))

                    # Extract and display matched pairs table
                    st.markdown("---")
                    if "MATCHED PAIRS" in report_text:
                        st.subheader("✅ Matched Pairs")

                        # Extract matched pairs from report
                        start_idx = report_text.find("MATCHED PAIRS")
                        end_idx = report_text.find("UNMATCHED INVOICES", start_idx)
                        if end_idx == -1:
                            end_idx = report_text.find("ERROR INVOICES", start_idx)
                        if end_idx == -1:
                            end_idx = len(report_text)

                        matched_section = report_text[start_idx:end_idx]

                        # Display as formatted table
                        st.text(matched_section)

                    # Extract and display unmatched invoices
                    st.markdown("---")
                    if "UNMATCHED INVOICES" in report_text:
                        st.subheader("⚠️ Unmatched Invoices")

                        start_idx = report_text.find("UNMATCHED INVOICES")
                        end_idx = report_text.find("UNMATCHED PAYMENTS", start_idx)
                        if end_idx == -1:
                            end_idx = report_text.find("ERROR INVOICES", start_idx)
                        if end_idx == -1:
                            end_idx = len(report_text)

                        unmatched_inv = report_text[start_idx:end_idx]
                        st.text(unmatched_inv)

                    # Extract and display unmatched payments
                    if "UNMATCHED PAYMENTS" in report_text:
                        st.subheader("⚠️ Unmatched Payments")

                        start_idx = report_text.find("UNMATCHED PAYMENTS")
                        end_idx = report_text.find("ERROR INVOICES", start_idx)
                        if end_idx == -1:
                            end_idx = report_text.find("ERROR PAYMENTS", start_idx)
                        if end_idx == -1:
                            end_idx = len(report_text)

                        unmatched_pay = report_text[start_idx:end_idx]
                        st.text(unmatched_pay)

                    # Display error records if present
                    if "ERROR INVOICES" in report_text or "ERROR PAYMENTS" in report_text:
                        st.markdown("---")
                        st.subheader("❌ Data Quality Issues")
                        st.warning("Some documents were skipped due to data quality issues. See details below.")

                        if "ERROR INVOICES" in report_text:
                            st.subheader("Error Invoices")
                            start_idx = report_text.find("ERROR INVOICES")
                            end_idx = report_text.find("ERROR PAYMENTS", start_idx)
                            if end_idx == -1:
                                end_idx = len(report_text)

                            error_inv = report_text[start_idx:end_idx]
                            st.text(error_inv)

                        if "ERROR PAYMENTS" in report_text:
                            st.subheader("Error Payments")
                            start_idx = report_text.find("ERROR PAYMENTS")
                            error_pay = report_text[start_idx:]
                            st.text(error_pay)

                    # Download button for full report
                    st.markdown("---")
                    st.download_button(
                        label="📥 Download Full Report",
                        data=report_text,
                        file_name=f"reconciliation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                        mime="text/plain"
                    )

                else:
                    st.error("Unexpected response format")
                    st.json(data)

        except requests.exceptions.ConnectionError:
            st.error(f"❌ Connection Error: Could not reach {base_url}")
            st.info("Make sure your invoice matching service is running on the configured URL.")
        except requests.exceptions.Timeout:
            st.error("❌ Request Timeout: The server took too long to respond.")
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.info("Check the console logs for more details.")

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center'>
    <p style='color: #888; font-size: 12px;'>
        Invoice Reconciliation Dashboard | Last updated: 2026-06-30
    </p>
</div>
""", unsafe_allow_html=True)
