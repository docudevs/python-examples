# DocuDevs Python Notebook Examples

Interactive Jupyter notebooks demonstrating how to use DocuDevs for document processing.

## Prerequisites

1. Install the SDK:

   ```bash
   pip install docu-devs-api-client pydantic
   ```

2. Get an API key from [app.docudevs.ai](https://app.docudevs.ai)

3. Set your API key:

   ```bash
   export DOCUDEVS_API_KEY="your-api-key-here"
   ```

## Notebooks

| Notebook | Description |
|----------|-------------|
| [01-basic-extraction.ipynb](01-basic-extraction.ipynb) | Extract structured data using prompts and Pydantic schemas |
| [02-map-reduce.ipynb](02-map-reduce.ipynb) | Process long documents (50+ pages) with chunking |
| [03-knowledge-search.ipynb](03-knowledge-search.ipynb) | Enrich extractions with your reference data |
| [04-operations.ipynb](04-operations.ipynb) | Error analysis and follow-up questions |

## Quick Start

```python
import os
from docudevs import DocuDevsClient
from pydantic import BaseModel

client = DocuDevsClient(token=os.getenv("DOCUDEVS_API_KEY"))

class Invoice(BaseModel):
    invoice_number: str
    date: str
    total: float

# Process a document
with open("invoice.pdf", "rb") as f:
    job_id = await client.submit_and_process_document(
        document=f.read(),
        document_mime_type="application/pdf",
        schema=Invoice.model_json_schema()
    )

# Get the result
result = await client.wait_until_ready(job_id, result_format="json")
invoice = Invoice(**result)
print(f"Invoice {invoice.invoice_number}: ${invoice.total}")
```

## Running the Notebooks

```bash
# Install Jupyter if needed
pip install jupyter

# Start Jupyter
jupyter notebook
```

Then open any notebook and run the cells. Make sure to set your API key in the first setup cell.

## Support

- [Documentation](https://docs.docudevs.ai)
- [API Reference](https://docs.docudevs.ai/openapi)
