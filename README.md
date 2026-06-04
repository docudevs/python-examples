# DocuDevs Python Examples

[![Docs](https://img.shields.io/badge/Docs-docs.docudevs.ai-blue)](https://docs.docudevs.ai)
[![PyPI](https://img.shields.io/pypi/v/docu-devs-api-client)](https://pypi.org/project/docu-devs-api-client/)
[![License](https://img.shields.io/github/license/docudevs/python-examples)](LICENSE)

Extract structured data from any document with a few lines of Python.

## Quick Start

1. Get your API key at [docudevs.ai](https://docudevs.ai)
2. Click any notebook below to open in Google Colab
3. Add your API key to Colab Secrets (🔑 sidebar → add `DOCUDEVS_API_KEY`)

## Notebooks

| # | Notebook | Description | Colab |
|---|----------|-------------|-------|
| 1 | [Basic Extraction](01-basic-extraction.ipynb) | Prompts + Pydantic schemas → typed objects | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/docudevs/python-examples/blob/main/01-basic-extraction.ipynb) |
| 2 | [Map-Reduce](02-map-reduce.ipynb) | Long documents (50+ pages) with chunking | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/docudevs/python-examples/blob/main/02-map-reduce.ipynb) |
| 3 | [Knowledge Search](03-knowledge-search.ipynb) | Enrich extractions with reference data | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/docudevs/python-examples/blob/main/03-knowledge-search.ipynb) |
| 4 | [Operations](04-operations.ipynb) | Error analysis & document Q&A | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/docudevs/python-examples/blob/main/04-operations.ipynb) |
| 5 | [Pipeline Extraction](05-pipeline-extraction.ipynb) | Classify, branch, and extract with pipeline mode | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/docudevs/python-examples/blob/main/05-pipeline-extraction.ipynb) |
| 6 | [Image Object Detection](06-source-locations.ipynb) | Detect objects in a soccer image and draw visual bounding boxes | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/docudevs/python-examples/blob/main/06-source-locations.ipynb) |
| 7 | [PDF Templates](07-pdf-template.ipynb) | Upload a fillable authorization PDF as a template, inspect fields, and fill it | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/docudevs/python-examples/blob/main/07-pdf-template.ipynb) |
| 8 | [PDF to AcroForm](08-pdf-acroform-metadata.ipynb) | Convert a complex medical PDF to AcroForm and inspect metadata/field definitions | [![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/docudevs/python-examples/blob/main/08-pdf-acroform-metadata.ipynb) |

## Local Setup

```bash
pip install docu-devs-api-client pydantic jupyter matplotlib pillow pypdf
export DOCUDEVS_API_KEY="your-api-key-here"
jupyter notebook
```

## Example

```python
from docudevs import DocuDevsClient
from pydantic import BaseModel

client = DocuDevsClient(token="your-api-key")

class Invoice(BaseModel):
    invoice_number: str
    date: str
    total: float

job_id = await client.submit_and_process_document(
    document=open("invoice.pdf", "rb").read(),
    document_mime_type="application/pdf",
    schema=Invoice.model_json_schema()
)

result = await client.wait_until_ready(job_id, result_format="json")
invoice = Invoice(**result)
print(f"Invoice {invoice.invoice_number}: ${invoice.total}")
```

## Resources

- [Documentation](https://docs.docudevs.ai)
- [API Reference](https://docs.docudevs.ai/openapi)
- [Python SDK on PyPI](https://pypi.org/project/docu-devs-api-client/)
